from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

# Jev 增强层：可选依赖。导入失败 / 没配 TYPESAFE_API_KEY / JEV_NEWS=0
# → 下面三个函数全部走原来的关键词与字面逻辑，行为不变。
try:
    from . import jev_news as _jev
except Exception:       # noqa: BLE001 - 增强件不许拖垮主链路
    _jev = None


POSITIVE_HINTS = (
    "签约",
    "中标",
    "增长",
    "上调",
    "创新高",
    "利好",
    "增持",
    "回购",
    "扭亏",
    "超预期",
)

NEGATIVE_HINTS = (
    "下调",
    "减持",
    "亏损",
    "暴跌",
    "诉讼",
    "风险",
    "违规",
    "处罚",
    "利空",
    "退市",
)


def _to_naive_local(dt: datetime) -> datetime:
    """统一转为本地时区的 naive datetime，便于与 datetime.now() 比较。"""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone().replace(tzinfo=None)


def parse_news_time(value: str | datetime | int | float | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_naive_local(value)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except Exception:
            return None

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("T", " ").replace("Z", "+00:00")
    full_fmts = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    )
    for fmt in full_fmts:
        try:
            return _to_naive_local(datetime.strptime(normalized, fmt))
        except Exception:
            continue

    # 常见月日格式（无年份），按当前年份补齐。
    for fmt in ("%m-%d %H:%M:%S", "%m-%d %H:%M", "%m/%d %H:%M:%S", "%m/%d %H:%M"):
        try:
            partial = datetime.strptime(normalized, fmt)
            now = datetime.now()
            return partial.replace(year=now.year)
        except Exception:
            continue

    try:
        return _to_naive_local(datetime.fromisoformat(normalized))
    except Exception:
        return None


def _exact_dedupe(items: list[dict]) -> list[dict]:
    """原逻辑：(source, external_id, title) 三元组全等才算重复。
    便宜且无副作用，先跑它把字面重复去掉，再交给语义层。"""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for it in items:
        source = str(it.get("source") or "")
        external_id = str(it.get("external_id") or "")
        title = str(it.get("title") or "")
        key = (source, external_id, title)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def dedupe_news_items(items: list[dict]) -> list[dict]:
    """签名与行为契约不变：进一个 list，出一个去重后的 list。
    ⚠ 2026-09-19 实测：仅靠字面全等，PanWatch /api/news 实时 40 条去掉 0 条；
      叠上事件级后 40 → 28。同一次回购/召回被四五家媒体各写一遍是常态。"""
    out = _exact_dedupe(items)
    if _jev is None or not _jev.enabled():
        return out
    try:
        return _jev.event_dedupe(out)
    except Exception:   # noqa: BLE001 - fail-open，增强层炸了照常返回
        return out


def _sentiment_from_text(text: str) -> str:
    pos = sum(1 for k in POSITIVE_HINTS if k in text)
    neg = sum(1 for k in NEGATIVE_HINTS if k in text)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def rank_news_items(items: list[dict], symbol: str = "") -> list[dict]:
    # 东财返回的 importance 恒为 0（实测 40/40），所以下面 `importance * 5.0`
    # 这一项一直是死的。这里把它填上，排序公式本身一个字不改。
    if _jev is not None and _jev.enabled():
        try:
            items = _jev.fill_importance(items)
        except Exception:   # noqa: BLE001 - fail-open
            pass

    def score(it: dict) -> tuple[float, float]:
        title = str(it.get("title") or "")
        content = str(it.get("content") or "")
        text = f"{title} {content}"
        importance = float(it.get("importance") or 0)
        s = importance * 5.0

        if symbol and symbol in str(it.get("symbols") or []):
            s += 2.0
        if any(k in title for k in ("重大", "业绩", "增持", "减持", "停牌", "解禁", "回购", "分红", "快报")):
            s += 2.0
        if "公告" in title:
            s += 1.0

        ts = parse_news_time(_item_time_value(it)) or datetime.min
        s2 = ts.timestamp() if ts != datetime.min else 0
        return s, s2

    return sorted(items, key=score, reverse=True)


def summarize_news_topics(items: list[dict], max_topics: int = 6) -> dict:
    if not items:
        return {
            "summary": "近期无显著新闻主题",
            "topics": [],
            "sentiment": "neutral",
            "counts": {"positive": 0, "negative": 0, "neutral": 0},
        }

    word_counter: Counter[str] = Counter()
    senti_counter: Counter[str] = Counter()

    # 批量问一次「对持股人是利好还是利空」；拿不到就逐条走关键词法。
    # ⚠ 关键词法分不清方向：「宁德时代减持湖南裕能」含「减持」判负面，
    #   但对宁德时代持有人那是它在卖别人。
    jev_senti: dict = {}
    if _jev is not None and _jev.enabled():
        try:
            jev_senti = _jev.batch_sentiment(items)
        except Exception:   # noqa: BLE001 - fail-open
            jev_senti = {}

    for it in items:
        title = str(it.get("title") or "")
        content = str(it.get("content") or "")
        text = f"{title} {content}".strip()
        sentiment = jev_senti.get(title) or _sentiment_from_text(text)
        # ⚠ 原版只把逐条判定喂给多数投票的汇总，从不存回 item —— 于是逐条准确率
        #   的改进（实测关键词 2/6 → Jev 5/6）在汇总层被冲掉，用户一点都看不到。
        #   存回去是纯增量（只新增一个 key），下游可用可不用。
        it.setdefault("sentiment", sentiment)
        senti_counter[sentiment] += 1

        words = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", title)
        for w in words:
            if w in ("公司", "公告", "今日", "消息", "显示", "发布", "表示", "相关"):
                continue
            word_counter[w] += 1

    topics = [w for w, _ in word_counter.most_common(max_topics)]
    if senti_counter["positive"] > senti_counter["negative"]:
        senti = "positive"
    elif senti_counter["negative"] > senti_counter["positive"]:
        senti = "negative"
    else:
        senti = "neutral"

    if topics:
        summary = f"主题集中在：{'、'.join(topics[: max_topics])}；整体情绪{('偏多' if senti == 'positive' else '偏空' if senti == 'negative' else '中性')}"
    else:
        summary = f"可用新闻较少，整体情绪{('偏多' if senti == 'positive' else '偏空' if senti == 'negative' else '中性')}"

    return {
        "summary": summary,
        "topics": topics,
        "sentiment": senti,
        "counts": {
            "positive": int(senti_counter["positive"]),
            "negative": int(senti_counter["negative"]),
            "neutral": int(senti_counter["neutral"]),
        },
    }


def _item_time_value(it: dict):
    return it.get("time") or it.get("publish_time") or it.get("published_at")


def news_item_to_rank_dict(item) -> dict:
    """NewsItem / SimpleNamespace / dict → ranker 用的 dict，保留额外字段。"""
    if isinstance(item, dict):
        d = dict(item)
    else:
        pt = getattr(item, "publish_time", None) or getattr(item, "time", None)
        d = {
            "source": str(getattr(item, "source", "") or ""),
            "external_id": str(getattr(item, "external_id", "") or ""),
            "title": str(getattr(item, "title", "") or ""),
            "content": str(getattr(item, "content", "") or ""),
            "publish_time": pt,
            "time": pt,
            "symbols": list(getattr(item, "symbols", None) or []),
            "importance": int(getattr(item, "importance", 0) or 0),
            "url": str(getattr(item, "url", "") or ""),
        }
    if not d.get("time"):
        d["time"] = d.get("publish_time") or d.get("published_at") or ""
    if d.get("symbols") is None:
        d["symbols"] = []
    try:
        d["importance"] = int(d.get("importance") or 0)
    except (TypeError, ValueError):
        d["importance"] = 0
    return d


def fill_missing_importance(items: list[dict]) -> list[dict]:
    """只填 importance 为 0 的条目；Jev 不可用时原样返回。"""
    if _jev is not None and _jev.enabled():
        try:
            return _jev.fill_importance(items)
        except Exception:  # noqa: BLE001 - fail-open
            pass
    return items


def enhance_news_items(
    items,
    *,
    symbol: str = "",
    with_sentiment: bool = True,
    max_items: int = 60,
) -> list[dict]:
    """采集结果的统一后处理：字面去重 → 截断 → 语义去重 → 填重要性并排序 → 情绪。

    超过 max_items 时先按时间截断，否则 Jev 会因上限直接跳过语义层。
    """
    rows = [news_item_to_rank_dict(it) for it in items or []]
    if not rows:
        return []
    rows = _exact_dedupe(rows)
    if len(rows) > max_items:
        rows = sorted(
            rows,
            key=lambda it: parse_news_time(_item_time_value(it)) or datetime.min,
            reverse=True,
        )[:max_items]
    rows = dedupe_news_items(rows)
    rows = rank_news_items(rows, symbol=symbol)
    if with_sentiment:
        summarize_news_topics(rows)
    return rows


def enhance_newsitem_objects(items, *, symbol: str = "", with_sentiment: bool = True):
    """对 NewsItem 列表做同样增强，返回新的 NewsItem（可带 sentiment 属性）。"""
    from src.platform.marketdata.collectors.news_collector import NewsItem

    out: list = []
    for d in enhance_news_items(items, symbol=symbol, with_sentiment=with_sentiment):
        pt = d.get("publish_time") or d.get("time")
        if not isinstance(pt, datetime):
            pt = parse_news_time(pt) or datetime.now()
        obj = NewsItem(
            source=str(d.get("source") or ""),
            external_id=str(d.get("external_id") or ""),
            title=str(d.get("title") or ""),
            content=str(d.get("content") or ""),
            publish_time=pt,
            symbols=list(d.get("symbols") or []),
            importance=int(d.get("importance") or 0),
            url=str(d.get("url") or ""),
        )
        if d.get("sentiment"):
            obj.sentiment = d["sentiment"]
        out.append(obj)
    return out
