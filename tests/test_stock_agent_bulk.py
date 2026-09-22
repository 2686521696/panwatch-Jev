"""批量绑定 Agent：只改目标绑定，保留其它 Agent 的调度配置，且不触发分析。"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.platform.persistence.database import Base
from src.platform.persistence.models import AgentConfig, Stock, StockAgent  # noqa: F401
from src.modules.market.api.stocks import (
    StockAgentBulkBind,
    StockAgentItem,
    StockAgentUpdate,
    bulk_bind_stock_agent,
    update_stock_agents,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _agent(db, name: str, display_name: str, kind: str = "workflow"):
    row = AgentConfig(name=name, display_name=display_name, kind=kind, visible=True, enabled=True)
    db.add(row)
    db.commit()
    return row


def _stock(db, symbol: str, name: str):
    row = Stock(symbol=symbol, name=name, market="CN")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _bindings(db, stock_id: int) -> dict[str, str]:
    rows = db.query(StockAgent).filter(StockAgent.stock_id == stock_id).all()
    return {row.agent_name: row.schedule or "" for row in rows}


def test_bulk_bind_keeps_other_agent_schedule_and_is_idempotent():
    db = _session()
    _agent(db, "intraday_monitor", "盘中监测")
    _agent(db, "tradingagents", "TradingAgents 深度分析")
    first = _stock(db, "600199", "金种子酒")
    second = _stock(db, "000002", "万科A")
    update_stock_agents(
        first.id,
        StockAgentUpdate(agents=[
            StockAgentItem(agent_name="intraday_monitor", schedule="*/5 9-15 * * 1-5"),
        ]),
        db,
    )

    enabled = bulk_bind_stock_agent(
        StockAgentBulkBind(stock_ids=[first.id, second.id, first.id], agent_name="tradingagents", enabled=True),
        db,
    )
    assert enabled["updated"] == 2
    assert enabled["missing_ids"] == []
    assert _bindings(db, first.id) == {
        "intraday_monitor": "*/5 9-15 * * 1-5",
        "tradingagents": "",
    }
    assert _bindings(db, second.id) == {"tradingagents": ""}

    again = bulk_bind_stock_agent(
        StockAgentBulkBind(stock_ids=[first.id, second.id], agent_name="tradingagents", enabled=True),
        db,
    )
    assert again["updated"] == 0
    assert _bindings(db, first.id)["intraday_monitor"] == "*/5 9-15 * * 1-5"

    disabled = bulk_bind_stock_agent(
        StockAgentBulkBind(stock_ids=[first.id, 99999], agent_name="tradingagents", enabled=False),
        db,
    )
    assert disabled["updated"] == 1
    assert disabled["missing_ids"] == [99999]
    assert _bindings(db, first.id) == {"intraday_monitor": "*/5 9-15 * * 1-5"}
    assert _bindings(db, second.id) == {"tradingagents": ""}
    db.close()


def test_bulk_bind_rejects_empty_unknown_and_internal_agents():
    db = _session()
    _agent(db, "news_digest", "新闻速递", kind="capability")
    stock = _stock(db, "600519", "贵州茅台")

    with pytest.raises(HTTPException) as empty:
        bulk_bind_stock_agent(StockAgentBulkBind(stock_ids=[], agent_name="intraday_monitor", enabled=True), db)
    assert empty.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        bulk_bind_stock_agent(StockAgentBulkBind(stock_ids=[stock.id], agent_name="missing", enabled=True), db)
    assert missing.value.status_code == 400

    with pytest.raises(HTTPException) as internal:
        bulk_bind_stock_agent(StockAgentBulkBind(stock_ids=[stock.id], agent_name="news_digest", enabled=True), db)
    assert internal.value.status_code == 400
    assert _bindings(db, stock.id) == {}
    db.close()
