"""Jev 卡片方向：只产出买入/观望/回避，失败时不抛错。"""

from types import SimpleNamespace

from src.modules.market import jev_news


class _Client:
    def __init__(self, choices):
        self.choices = choices
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def system_one(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=self.choices)


def _answer(choice, confidence=0.9):
    return SimpleNamespace(choice=choice, confidence=confidence)


def test_judge_directions_maps_choices_and_low_confidence_to_watch(monkeypatch):
    client = _Client({
        "d0": _answer("avoid", 0.8),
        "d1": _answer("buy", 0.2),
        "d2": _answer("maybe", 0.9),
    })
    monkeypatch.setattr(jev_news, "_enabled", lambda: True)
    monkeypatch.setattr(jev_news, "_client", lambda: client)
    monkeypatch.setattr(jev_news, "_build_choice", lambda instructions, criteria: (instructions, criteria))

    result = jev_news.judge_directions([
        {"symbol": "600519", "name": "贵州茅台", "change_pct": 1.2, "technical": "多头", "headlines": ["提价"]},
        {"symbol": "000002", "name": "万科A", "change_pct": -0.4, "technical": "无", "headlines": []},
        {"symbol": "00700", "name": "腾讯", "change_pct": None, "technical": "无", "headlines": []},
    ])

    assert result["600519"]["action"] == "avoid"
    assert result["600519"]["action_label"] == "回避"
    assert result["000002"]["action"] == "watch"
    assert "置信度不足" in result["000002"]["reason"]
    assert result["00700"]["action"] == "watch"
    assert "涨跌未知" in result["00700"]["reason"]
    assert client.calls[0]["model"] == "jev-latest"


def test_judge_directions_fail_open(monkeypatch):
    monkeypatch.setattr(jev_news, "_enabled", lambda: False)
    assert jev_news.judge_directions([{"symbol": "600519"}]) == {}

    monkeypatch.setattr(jev_news, "_enabled", lambda: True)

    class Broken:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def system_one(self, **kwargs):
            raise RuntimeError("down")

    monkeypatch.setattr(jev_news, "_client", lambda: Broken())
    monkeypatch.setattr(jev_news, "_build_choice", lambda instructions, criteria: criteria)
    assert jev_news.judge_directions([{"symbol": "600519", "name": "茅台"}]) == {}
