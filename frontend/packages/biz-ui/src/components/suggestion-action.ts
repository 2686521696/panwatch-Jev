export type SuggestionAction =
  | 'buy'
  | 'add'
  | 'reduce'
  | 'sell'
  | 'hold'
  | 'watch'
  | 'alert'
  | 'avoid'

// 和行情同一套：红 = 做多，绿 = 回避/卖出。买入和回避不能再都用实心红。
export const suggestionActionColors: Record<SuggestionAction, string> = {
  buy: 'bg-rose-600 text-white',
  add: 'bg-rose-500/15 text-rose-700 ring-1 ring-rose-500/40',
  reduce: 'bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/40',
  sell: 'bg-emerald-800 text-white',
  hold: 'bg-amber-500/15 text-amber-800 ring-1 ring-amber-500/40',
  watch: 'bg-slate-500/10 text-slate-600 ring-1 ring-slate-400/50',
  alert: 'bg-sky-600 text-white',
  avoid: 'bg-emerald-600 text-white',
}

export const suggestionActionLabels: Record<SuggestionAction, string> = {
  buy: '买入',
  add: '加仓',
  reduce: '减仓',
  sell: '卖出',
  hold: '持有',
  watch: '观望',
  avoid: '回避',
  alert: '提醒',
}

export function normalizeSuggestionAction(action?: string, label?: string): SuggestionAction | null {
  const raw = (action || label || '').toLowerCase()
  if (!raw) return null
  if (raw === 'buy') return 'buy'
  if (raw === 'add' || raw === 'increase') return 'add'
  if (raw === 'reduce' || raw === 'decrease') return 'reduce'
  if (raw === 'sell') return 'sell'
  if (raw === 'hold') return 'hold'
  if (raw === 'watch' || raw === 'neutral') return 'watch'
  if (raw === 'avoid') return 'avoid'
  if (raw === 'alert') return 'alert'
  if (/买入|买|建仓/.test(raw)) return 'buy'
  if (/加仓|增持|补仓/.test(raw)) return 'add'
  if (/减仓|减持/.test(raw)) return 'reduce'
  if (/清仓|卖出|止损|卖/.test(raw)) return 'sell'
  if (/持有|持仓/.test(raw)) return 'hold'
  if (/观望|中性|等待/.test(raw)) return 'watch'
  if (/回避|规避|避免/.test(raw)) return 'avoid'
  return null
}

export function resolveSuggestionAction(action?: string, label?: string): SuggestionAction {
  return normalizeSuggestionAction(action, label) || 'watch'
}

export function resolveSuggestionLabel(action?: string, label?: string, fallback = '观望'): string {
  const normalized = normalizeSuggestionAction(action, label)
  if (normalized) return suggestionActionLabels[normalized] || fallback
  return String(label || '').trim() || fallback
}

export function resolveSuggestionColorClass(action?: string, label?: string): string {
  const normalized = resolveSuggestionAction(action, label)
  return suggestionActionColors[normalized] || suggestionActionColors.watch
}
