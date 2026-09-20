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

        ts = parse_news_time(str(it.get("time") or "")) or datetime.min
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
