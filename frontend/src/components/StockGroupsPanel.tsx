import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react'
import { fetchAPI } from '@panwatch/api'
import { Button } from '@panwatch/base-ui/components/ui/button'
import { Input } from '@panwatch/base-ui/components/ui/input'
import { useToast } from '@panwatch/base-ui/components/ui/toast'
import { useLocalStorage } from '@/lib/utils'

export interface StockGroupMember {
  id: number
  stock_id: number
  symbol: string
  name: string
  market: string
  sort_order: number
}

export interface StockGroup {
  id: number
  name: string
  sort_order: number
  members: StockGroupMember[]
}

interface Quote {
  current_price: number | null
  change_pct: number | null
}

interface Props {
  quotes: Record<string, Quote>
  onOpenStock: (symbol: string, market: string, name?: string, hasPosition?: boolean) => void
  onStocksChanged?: () => void
}

function changeAmount(price: number | null, pct: number | null): number | null {
  if (price == null || pct == null) return null
  const prev = price / (1 + pct / 100)
  if (!Number.isFinite(prev)) return null
  return price - prev
}

function tone(pct: number | null): string {
  if (pct == null || pct === 0) return 'text-muted-foreground'
  return pct > 0 ? 'text-rose-500' : 'text-emerald-500'
}

function fmt(value: number | null, digits = 2, signed = false): string {
  if (value == null || Number.isNaN(value)) return '--'
  const text = value.toFixed(digits)
  if (!signed) return text
  return value > 0 ? `+${text}` : text
}

export default function StockGroupsPanel({ quotes, onOpenStock, onStocksChanged }: Props) {
  const { toast } = useToast()
  const [groups, setGroups] = useState<StockGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [collapsed, setCollapsed] = useLocalStorage<number[]>('panwatch_stock_groups_collapsed', [])

  const collapsedSet = useMemo(() => new Set(collapsed), [collapsed])

  const load = useCallback(async () => {
    try {
      const data = await fetchAPI<StockGroup[]>('/stocks/groups')
      setGroups(data)
    } catch (error) {
      toast(error instanceof Error ? error.message : '加载分组失败', 'error')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    load()
  }, [load])

  const toggle = (id: number) => {
    setCollapsed(prev => (prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id]))
  }

  const createGroup = async () => {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    try {
      await fetchAPI('/stocks/groups', { method: 'POST', body: JSON.stringify({ name }) })
      setNewName('')
      await load()
      toast('分组已创建', 'success')
    } catch (error) {
      toast(error instanceof Error ? error.message : '创建分组失败', 'error')
    } finally {
      setCreating(false)
    }
  }

  const removeGroup = async (group: StockGroup) => {
    if (!confirm(`删除分组「${group.name}」？股票仍会留在关注列表。`)) return
    try {
      await fetchAPI(`/stocks/groups/${group.id}`, { method: 'DELETE' })
      await load()
    } catch (error) {
      toast(error instanceof Error ? error.message : '删除分组失败', 'error')
    }
  }

  const removeMember = async (group: StockGroup, member: StockGroupMember) => {
    try {
      await fetchAPI(`/stocks/groups/${group.id}/stocks/${member.stock_id}`, { method: 'DELETE' })
      await load()
      onStocksChanged?.()
    } catch (error) {
      toast(error instanceof Error ? error.message : '移出分组失败', 'error')
    }
  }

  if (loading) {
    return <div className="card p-6 text-[13px] text-muted-foreground">分组加载中…</div>
  }

  return (
    <div className="space-y-3">
      <div className="card p-3 flex flex-col sm:flex-row sm:items-center gap-2">
        <Input
          value={newName}
          onChange={event => setNewName(event.target.value)}
          placeholder="新分组名称，例如 白酒"
          className="h-9"
          onKeyDown={event => {
            if (event.key === 'Enter') {
              event.preventDefault()
              createGroup()
            }
          }}
        />
        <Button type="button" className="shrink-0" onClick={createGroup} disabled={creating || !newName.trim()}>
          <Plus className="w-4 h-4" /> 新建分组
        </Button>
      </div>

      {groups.length === 0 ? (
        <div className="card p-8 text-center text-[13px] text-muted-foreground">还没有分组</div>
      ) : groups.map(group => {
        const open = !collapsedSet.has(group.id)
        return (
          <section key={group.id} className="card overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border/40">
              <button
                type="button"
                className="flex-1 flex items-center justify-between text-left"
                onClick={() => toggle(group.id)}
              >
                <span className="text-[15px] font-medium text-foreground">
                  {group.name}
                  <span className="ml-2 text-[11px] text-muted-foreground font-normal">{group.members.length}</span>
                </span>
                {open ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
              </button>
              <Button variant="ghost" size="icon" className="h-7 w-7 hover:text-destructive" title="删除分组" onClick={() => removeGroup(group)}>
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>
            {open && (
              group.members.length === 0 ? (
                <div className="px-4 py-6 text-[13px] text-muted-foreground">这个分组还没有股票</div>
              ) : (
                <div>
                  {group.members.map(member => {
                    const quote = quotes[`${member.market}:${member.symbol}`]
                    const pct = quote?.change_pct ?? null
                    const price = quote?.current_price ?? null
                    const delta = changeAmount(price, pct)
                    const color = tone(pct)
                    return (
                      <div
                        key={member.id}
                        className="grid grid-cols-[minmax(0,1fr)_4.2rem_3.4rem_4.4rem_1.5rem] items-center gap-2 px-4 py-3 border-t border-border/30 first:border-t-0 hover:bg-accent/20"
                      >
                        <button
                          type="button"
                          className="min-w-0 text-left"
                          onClick={() => onOpenStock(member.symbol, member.market, member.name, false)}
                        >
                          <div className="text-[15px] text-foreground truncate">{member.name}</div>
                          <div className="text-[12px] text-muted-foreground font-mono">{member.symbol}</div>
                        </button>
                        <div className={`text-right font-mono text-[15px] font-semibold ${color}`}>{fmt(price)}</div>
                        <div className={`text-right font-mono text-[13px] ${color}`}>{fmt(delta, 2, true)}</div>
                        <div className={`text-right font-mono text-[13px] ${color}`}>
                          {pct == null ? '--' : `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`}
                        </div>
                        <button
                          type="button"
                          className="text-muted-foreground/50 hover:text-destructive"
                          title="移出分组"
                          onClick={() => removeMember(group, member)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    )
                  })}
                </div>
              )
            )}
          </section>
        )
      })}
    </div>
  )
}
