"""账户接口。"""
from fastapi import APIRouter
from sqlmodel import delete, select

from app.core.response import ok
from app.models.db import Account, Order, Position, Trade, get_session
from app.models.schemas import AccountReset
from app.services.portfolio import build_account_snapshot

router = APIRouter(prefix="/api/v1/account", tags=["account"])


@router.get("")
async def get_account():
    snapshot = await build_account_snapshot()
    return ok(snapshot)


@router.post("/reset")
async def reset_account(body: AccountReset):
    with get_session() as session:
        # 清空持仓 / 订单 / 流水
        session.exec(delete(Position))
        session.exec(delete(Order))
        session.exec(delete(Trade))
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
