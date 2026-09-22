"""自选分组：创建、重复加入、一只股票进多个分组。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.platform.persistence.database import Base
from src.platform.persistence.models import Stock, StockGroup, StockGroupMember  # noqa: F401
from src.modules.market.api.stocks import add_stock_to_group, create_stock_group, list_stock_groups


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_stock_can_belong_to_more_than_one_group():
    db = _session()
    liquor = create_stock_group("白酒", db)
    drinks = create_stock_group("饮料", db)

    add_stock_to_group(liquor["id"], "603711", "香飘飘", "CN", db)
    add_stock_to_group(drinks["id"], "603711", "香飘飘", "CN", db)
    add_stock_to_group(drinks["id"], "603711", "香飘飘", "CN", db)

    groups = {item["name"]: item for item in list_stock_groups(db)}
    assert [member["symbol"] for member in groups["白酒"]["members"]] == ["603711"]
    assert [member["symbol"] for member in groups["饮料"]["members"]] == ["603711"]
    assert db.query(Stock).filter(Stock.symbol == "603711").count() == 1
    db.close()
