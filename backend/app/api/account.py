"""账户接口。"""
from fastapi import APIRouter, Query
from sqlmodel import delete, select

from app.core.response import ok
from app.models.db import Account, EquitySnapshot, Order, Position, Trade, get_session
from app.models.schemas import AccountReset
from app.services.portfolio import build_account_snapshot, get_equity_curve

router = APIRouter(prefix="/api/v1/account", tags=["account"])


@router.get("")
async def get_account():
    snapshot = await build_account_snapshot()
    return ok(snapshot)


@router.get("/equity")
async def get_equity(
    range: str = Query("1D", description="1H | 1D | 1W | 1M | ALL"),
):
    """返回资产净值曲线数据（供前端 Dashboard 绘图用）。"""
    return ok(get_equity_curve(range))


@router.post("/reset")
async def reset_account(body: AccountReset):
    with get_session() as session:
        # 清空持仓 / 订单 / 流水 / 历史净值曲线（新起点）
        session.exec(delete(Position))
        session.exec(delete(Order))
        session.exec(delete(Trade))
        session.exec(delete(EquitySnapshot))
        acc = session.exec(select(Account).where(Account.id == 1)).first()
        if acc is None:
            acc = Account(id=1, cash=body.initial_capital, initial_capital=body.initial_capital)
        else:
            acc.cash = body.initial_capital
            acc.initial_capital = body.initial_capital
        session.add(acc)
        session.commit()
    snapshot = await build_account_snapshot()
    return ok(snapshot, message="account reset")
