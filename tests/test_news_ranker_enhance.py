"""新闻后处理：去重、截断、情绪写入，不依赖 Jev 网络。"""

from datetime import datetime, timedelta

from src.modules.market.news_ranker import enhance_news_items, enhance_newsitem_objects
from src.platform.marketdata.collectors.news_collector import NewsItem


def test_enhance_news_items_exact_dedupes_and_writes_sentiment():
    now = datetime(2026, 9, 21, 15, 0)
    items = [
        {
            "source": "xueqiu",
            "external_id": "1",
            "title": "公司回购股份",
            "content": "利好回购",
            "publish_time": now,
            "symbols": ["600519"],
            "importance": 0,
            "url": "http://a",
        },
        {
            "source": "xueqiu",
            "external_id": "1",
            "title": "公司回购股份",
            "content": "利好回购",
            "publish_time": now,
            "symbols": ["600519"],
            "importance": 0,
            "url": "http://a",
        },
        {
            "source": "eastmoney",
            "external_id": "2",
            "title": "股东拟减持",
            "content": "减持计划",
            "publish_time": now - timedelta(hours=1),
            "symbols": ["600519"],
            "importance": 0,
            "url": "http://b",
        },
    ]

    out = enhance_news_items(items, symbol="600519")

    assert len(out) == 2
    assert all("sentiment" in row for row in out)
    assert out[0]["sentiment"] in ("positive", "negative", "neutral")


def test_enhance_news_items_caps_before_semantic_layer():
    now = datetime(2026, 9, 21, 15, 0)
    items = [
        {
            "source": "xueqiu",
            "external_id": str(i),
            "title": f"标题{i}",
            "content": "",
            "time": now - timedelta(minutes=i),
            "importance": 0,
            "symbols": ["000001"],
            "url": "",
        }
        for i in range(80)
    ]

    out = enhance_news_items(items, max_items=10)

    assert len(out) <= 10


def test_enhance_newsitem_objects_roundtrip():
    items = [
        NewsItem(
            source="eastmoney",
            external_id="ann-1",
            title="重大资产重组",
            content="",
            publish_time=datetime(2026, 9, 21, 10, 0),
            symbols=["000002"],
            importance=0,
            url="http://x",
        )
    ]

    out = enhance_newsitem_objects(items, symbol="000002")

    assert len(out) == 1
    assert isinstance(out[0], NewsItem)
    assert out[0].title == "重大资产重组"
    assert hasattr(out[0], "sentiment")
