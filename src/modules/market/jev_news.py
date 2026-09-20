# -*- coding: utf-8 -*-
"""PanWatch news_ranker 的 Jev 增强层。

设计约束（照抄 PanWatch 的现状，不许改它上层代码）：
  * 三个公开函数签名完全不变：dedupe_news_items / rank_news_items / summarize_news_topics
  * **fail-open**：没配 key、网络炸、限流、超时 —— 一律退回原来的关键词/字面逻辑。
    这是增强件，不是闭环件；它自己炸了不许拖垮别人在跑的盯盘系统。
  * 不新增硬依赖：typesafe_sdk 导入失败就整层静默关闭。
  * 环境变量 JEV_NEWS=0 可一键关掉，出问题时不用改代码回滚。

实测依据（2026-09-19，PanWatch /api/news 实时 40 条）：
  原 dedupe_news_items  40 → 40（去掉 0）—— 键是 (source, external_id, title) 全等，
                                          同一事件不同媒体不同标题，一条都碰不到。
  本层 事件级去重        40 → 28（并掉 12）—— 宁德时代回购 ×4、比亚迪召回 ×5、
                                          腾讯回购 ×2、苹果维修 ×2、茅台发货仓 ×2。
  原关键词情绪           前 20 条：正面 5 / 负面 1 / 中性 14（70% 判不出）——
                        表里没有「召回」「抛售」「下降」，且分不清方向：
                        「宁德时代减持湖南裕能」对宁德时代持有人不是利空。
"""
from __future__ import annotations

import itertools
import logging
import os
import re
import threading

log = logging.getLogger(__name__)

MODEL = "jev-latest"
SAME_EVENT = 0.50          # 同事件阈值；0.55/0.59 那档是真实边界案例，调高会拆开
PAIR_MIN_SHARED = 1        # 进候选至少共享几个 2-gram；=2 实测会漏真重复
PAIRS_PER_REQ = 120        # 每问约 200 tok，单请求上限 64k，留足余量
MAX_ITEMS = 60             # 单次批处理上限，超出的按原逻辑走，避免 O(n²) 失控

_LOCK = threading.Lock()
_cache: dict = {}
_WARNED = False


def _enabled() -> bool:
    if os.environ.get("JEV_NEWS", "1") == "0":
        return False
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def _client():
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except Exception as e:                       # 没装 SDK / 初始化失败
        # ⚠ 真机 2026-09-19：typesafe_sdk 装错了 venv，这里静默返回 None，
        #   于是整层 fail-open 空转——Agent 照常跑完、报告照出，日志里一个字都没有，
        #   我以为补丁在生效。「依赖没装」和「临时故障」降级得一模一样是个设计缺陷。
        #   现在第一次失败会 WARNING 吼一次（之后降级为 debug，避免刷屏）。
        global _WARNED
        if not _WARNED:
            _WARNED = True
            log.warning("[JEV] 增强层不可用，已退回原关键词/字面逻辑：%s "
                        "（如需启用：pip install typesafe-sdk 并设置 TYPESAFE_API_KEY）", e)
        else:
            log.debug("Jev 不可用: %s", e)
        return None


def _grams(text: str, n: int = 2) -> set:
    t = re.sub(r"[^一-鿿0-9A-Za-z]", "", text or "")
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


# ----------------------------------------------------------------- 事件级去重
_DEDUP_CRIT = {
    "true": "报道的是同一个【具体事件】：同一次公告、同一笔交易、同一场发布、"
            "同一句表态，只是不同媒体的不同写法。",
    # ⚠ 没有下面这半句，「去宁化」那种持续多天的叙事线会被吞成一大簇，
    #   而同一话题又另起一簇，不自洽。实测：加上后离散事件合并不受影响
    #   （0.92/0.85/0.89 几乎不动），叙事线的错误合并断开（0.71→0.37）。
    "false": "不是同一个具体事件。包括：两件不同的事；或虽然围绕同一个【话题/趋势】，"
             "但各自报道的是不同的事实或不同的评论。",
}


def event_dedupe(items: list[dict]) -> list[dict]:
    """同一件事、不同措辞。原 dedupe 只认字面全等，抓不到跨媒体转载。"""
    if len(items) < 2 or len(items) > MAX_ITEMS:
        return items
    c = _client()
    if c is None:
        return items

    T = [str(it.get("title") or "") for it in items]
    S = [str(it.get("symbols") or "") for it in items]
    G = [_grams(t) for t in T]
    # 代码侧先分块：跨股票不可能同事件；没共享 2-gram 的也不可能。
    # 实测把全量两两降两个数量级（1953 → 405 对），且真重复 20/20 不漏。
    cand = [(i, j) for i, j in itertools.combinations(range(len(T)), 2)
            if S[i] == S[j] and len(G[i] & G[j]) >= PAIR_MIN_SHARED]
    if not cand:
        return items

    try:
        from typesafe_sdk import Noul
        same = {}
        with c:
            for k in range(0, len(cand), PAIRS_PER_REQ):
                batch = cand[k:k + PAIRS_PER_REQ]
                # ⚠ 别改成 `标题列表[i]` 这种位置索引：实测 66 对里假阳 17 个
                #   （「召回18万辆」vs「欧洲设四家工厂」= 0.96）。模型数不准列表下标。
                r = c.system_one(
                    state={"说明": "判断两条新闻标题是否报道同一件事"}, model=MODEL,
                    questions={f"p{i}_{j}": Noul(
                        instructions=(f"以下两条新闻标题报道的是【同一件事】吗？\n"
                                      f"标题甲：{T[i]}\n标题乙：{T[j]}"),
                        criteria=_DEDUP_CRIT) for i, j in batch})
                for i, j in batch:
                    same[(i, j)] = r.nouls[f"p{i}_{j}"].noul
    except Exception as e:
        log.warning("Jev 事件去重失败，保留原结果: %s", e)   # fail-open
        return items

    heads = []
    for i in range(len(T)):
        # 只跟簇首比，不做传递闭包（会链式过并）
        if not any(same.get((min(h, i), max(h, i)), 0.0) > SAME_EVENT for h in heads):
            heads.append(i)
    log.info("[JEV] event_dedupe %d -> %d (候选对 %d)", len(items), len(heads), len(cand))
    return [items[h] for h in heads]


# ----------------------------------------------------------------- 重要性打分
_MAT_LEVELS = ["没有新信息：无关、重复或无意义。",
               "少量背景：细节补充，不改变判断。",
               "实质信息：具体数字、具体决定或具体事件。",
               "重大信息：可能改变公司前景的披露。"]


def fill_importance(items: list[dict]) -> list[dict]:
    """把 importance 填上。

    ⚠ 不改 rank_news_items 的公式——它本来就有 `importance * 5.0`，
      只是东财返回的 importance 恒为 0（实测 40/40 条都是 0），这一项是死的。
      填字段比改公式侵入小得多。
    """
    todo = [it for it in items if not float(it.get("importance") or 0)][:MAX_ITEMS]
    if not todo:
        return items
    c = _client()
    if c is None:
        return items
    try:
        from typesafe_sdk import Score
        with c:
            r = c.system_one(
                state={"说明": "评估新闻对持股人的信息价值"}, model=MODEL,
                questions={f"m{k}": Score(
                    instructions=(f"对已持有该股票的人，这条新闻提供了多少值得决策参考的"
                                  f"新信息？\n标题：{it.get('title') or ''}"),
                    criteria=_MAT_LEVELS) for k, it in enumerate(todo)})
        for k, it in enumerate(todo):
            # ⚠ 真机 2026-09-19：第一版写成 round(score/3, 4) 这样的【浮点】，
            #   因为我只看了 rank_news_items 里的 `importance * 5.0` 就认定契约。
            #   实际 grep 出五个消费者，还有一个是 daily_report.py:307
            #       "⭐" * (n.get("importance") or 0)
            #   —— 星星数，必须是 int。浮点让整个 daily_report agent 崩掉：
            #   TypeError: can't multiply sequence by non-int of type 'float'。
            #   本仓 §4「改之前先 grep 有没有第二处」，我没 grep。
            #   契约：小整数，>=2 视为重要（daily_report:323 / context_builder:493）。
            #   Score 恰好 4 档 0-3，档位 2「实质信息」正好对上那个门槛。
            it["importance"] = max(0, min(3, int(round(r.scores[f"m{k}"].score))))
    except Exception as e:
        log.warning("Jev 重要性打分失败，importance 保持原值: %s", e)   # fail-open
    return items


# ----------------------------------------------------------------- 情绪
def batch_sentiment(items: list[dict]) -> dict:
    """→ {title: 'positive'|'negative'|'neutral'}；失败返回 {} 让调用方退回关键词法。

    ⚠ 问的是【对持股人】是利好还是利空，不是文本情绪。
      关键词法分不清方向：「宁德时代减持湖南裕能」里有「减持」判负面，
      但对宁德时代持有人那是它在卖别人，不是利空。
    """
    if not items or len(items) > MAX_ITEMS or not _enabled():
        return {}
    c = _client()
    if c is None:
        return {}
    try:
        from typesafe_sdk import Choice
        opts = {"positive": "对持有该股票的人是利好。",
                "negative": "对持有该股票的人是利空。",
                "neutral": "中性，或无法从标题判断方向。"}
        with c:
            r = c.system_one(
                state={"说明": "判断新闻对持股人的方向"}, model=MODEL,
                questions={f"s{k}": Choice(
                    instructions=(f"这条新闻对【持有 {it.get('symbols') or '该股票'} 的人】"
                                  f"是利好还是利空？\n标题：{it.get('title') or ''}"),
                    criteria=opts) for k, it in enumerate(items)})
        out = {}
        for k, it in enumerate(items):
            a = r.choices[f"s{k}"]
            # 置信度低就不表态——本仓实测 conf 反映的是「问题有没有明确答案」
            out[str(it.get("title") or "")] = a.choice if a.confidence >= 0.50 else "neutral"
        return out
    except Exception as e:
        log.warning("Jev 情绪判定失败，退回关键词法: %s", e)   # fail-open
        return {}


def enabled() -> bool:
    return _enabled()
