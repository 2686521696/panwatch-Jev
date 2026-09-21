# PanWatch + Jev

> Fork of **[TNT-Likely/PanWatch](https://github.com/TNT-Likely/PanWatch)** (MIT, © 2026 sunxiao0721).
> Upstream docs are preserved verbatim in [README.upstream.md](README.upstream.md).
>
> 本仓库是 **[TNT-Likely/PanWatch](https://github.com/TNT-Likely/PanWatch)** 的 fork（MIT 许可）。
> 上游原始文档完整保留在 [README.upstream.md](README.upstream.md)。

---

## What this fork changes / 这个 fork 改了什么

One thing only: the news layer (`src/modules/market/news_ranker.py`) gains a
[TypeSafe Jev](https://typesafe.ai) enhancement layer. Everything else is upstream, untouched.

只改一处：新闻层（`src/modules/market/news_ranker.py`）加了一个 Jev 增强层。其余全部保持上游原样。

| Function | Upstream | With this fork |
| --- | --- | --- |
| `dedupe_news_items` | exact `(source, external_id, title)` tuple match | + semantic same-event clustering |
| `rank_news_items` | formula unchanged, but `importance` is always 0 from the data source | formula unchanged; `importance` filled in |
| `summarize_news_topics` | 20 hard-coded sentiment keywords | asks whether an item is good or bad **for a holder** |

| 函数 | 上游行为 | 本 fork |
| --- | --- | --- |
| `dedupe_news_items` | `(source, external_id, title)` 三元组全等 | 叠加语义事件级去重 |
| `rank_news_items` | 公式不变，但数据源给的 `importance` 恒为 0 | 公式一字不改，把 `importance` 填上 |
| `summarize_news_topics` | 20 个硬编码情绪关键词 | 改问「对持股人是利好还是利空」 |

## Measured on live data / 实测

Against 40 live items from this app's own `/api/news` (2026-09-19):

```
upstream dedupe_news_items   40 → 40   (removed 0)
this fork                    40 → 28   (merged 12)
```

The 12 merges: four near-identical CATL buyback headlines, five BYD recall
headlines, two Tencent buyback, two Moutai warehouse items — the same event
reported by different outlets, which a tuple match cannot see.

Per-item sentiment on a hand-labelled set: keyword method 2/6, this fork 5/6.
The keyword list has no entry for 召回 (recall), 抛售 (sell-off) or 下降
(decline), and cannot tell direction — 「宁德时代减持湖南裕能」 contains 减持
but CATL is the *seller*, which is not bearish for a CATL holder.

对同一批数据：上游去重去掉 0 条，本 fork 并掉 12 条（同一次回购/召回被四五家媒体各写一遍）。
逐条方向判定：关键词法 2/6，本 fork 5/6。

## Fail-open by design / 降级设计

This is an **enhancement, not a gate**. Missing key, missing SDK, network error,
rate limit — all fall back to the original keyword/tuple logic. The agent still
runs and still produces a report.

没有 key、没装 SDK、网络故障、限流 —— 一律退回上游原逻辑，Agent 照常跑完。

```bash
# .env or process env / 写进 .env 或 export 均可
JEV_NEWS=0            # hard off, no code change / 一键关闭
```

| State / 状态 | Result / 结果 |
| --- | --- |
| disabled or no key / 关闭或无 key | byte-identical to upstream / 与上游逐字节一致 |
| invalid key, 401 / key 无效 | warns, degrades, does not raise / 告警降级，不抛异常 |
| valid key / key 正常 | event dedup active / 事件去重生效 |

## Setup / 安装

```bash
docker compose up -d          # or the upstream docker run, see README.upstream.md

pip install typesafe-sdk      # required for the Jev layer / Jev 层需要
# TYPESAFE_API_KEY=...        # in .env (see .env.example) or export
```

**Verify the layer is actually live.** A missing dependency degrades silently by
design, so confirm in the logs:

**务必确认它真的在跑。** 依赖缺失是静默降级的，看日志确认：

```
[JEV] event_dedupe 9 -> 3 (候选对 12)
```

Seeing `[JEV] 增强层不可用` instead means the SDK is missing or the key is unset.

### LLM provider note / 模型选择

Any OpenAI-compatible endpoint works. But if your provider serves a reasoning
model that leaks chain-of-thought into `message.content`, the report body shown
to the user becomes that reasoning dump — the JSON tag block still parses, so no
mechanical check catches it. Prefer a non-reasoning model.

任何 OpenAI 兼容端点都可以。但如果模型把思维链混进 `message.content`，
渲染给用户的报告正文就变成一堆推理过程 —— 而 JSON 标记块照样能解析，
机械检查发现不了。优先选非思考型模型。

## Honest limits / 已知边界

- Event dedup runs on at most 60 items per call; beyond that the list passes through unchanged.
- Pairwise comparison is `O(n²)` before code-side blocking. Blocking cuts it ~99% but is verified on a 12-item labelled set only.
- No cross-call cache: `context_builder` invokes dedup 3–4 times per symbol, so overlapping lists get re-asked.
- Exercised end-to-end through `daily_report` only. `premarket_outlook` and `intraday_monitor` share the same `context_builder` path but were not run.
- Typed output guarantees the interface, not the truth. Validate thresholds on your own data.

- 事件去重单次上限 60 条，超出原样放行。
- 两两比对在代码分块前是 `O(n²)`；分块降约 99%，但只在 12 条标注集上验证过。
- 无跨调用缓存：`context_builder` 每支票调 3~4 次去重，重叠列表会被重复问。
- 端到端只跑通了 `daily_report`；`premarket_outlook` / `intraday_monitor` 走同一条路径但未实跑。
- 类型化输出保证的是接口，不是真相。阈值请在你自己的数据上标定。

## License / 许可

MIT, inherited from upstream — see [LICENSE](LICENSE), copyright © 2026 sunxiao0721.
Changes in this fork are released under the same licence.

MIT，继承自上游。见 [LICENSE](LICENSE)，版权归原作者 sunxiao0721。本 fork 的改动同样以 MIT 发布。
