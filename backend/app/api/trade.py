"""交易接口。"""
from fastapi import APIRouter, HTTPException, Query

from app.core.response import ok
from app.models.schemas import OrderCreate
from app.services import matching

router = APIRouter(prefix="/api/v1", tags=["trade"])


@router.post("/orders")
async def create_order(body: OrderCreate):
    try:
        data = await matching.place_order(
            symbol=body.symbol,
            side=body.side,
            type_=body.type,
            quantity=body.quantity,
            price=body.price,
        )
        return ok(data)
    except matching.MatchingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/orders")
async def get_orders(status: str | None = Query(None, pattern="^(open|filled|cancelled)$")):
    return ok(matching.list_orders(status=status))


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: int):
    try:
        data = matching.cancel_order(order_id)
        return ok(data)
    except matching.MatchingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trades")
async def get_trades():
    return ok(matching.list_trades())


@router.get("/positions")
async def get_positions():
    # 复用 portfolio 快照里的 positions 字段
    from app.services.portfolio import build_account_snapshot
    snap = await build_account_snapshot()
    return ok(snap["positions"])
