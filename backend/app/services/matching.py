"""
模拟撮合引擎。
- 市价单：立即以当前 ticker 成交
- 限价单：开单进入 open；由后台轮询任务按最新价判定成交
成交逻辑：
  buy  limit: last_price <= order.price → 成交
  sell limit: last_price >= order.price → 成交
"""
import asyncio
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models.db import Account, Order, Position, Trade, get_session
from app.services import exchange


class MatchingError(Exception):
    pass


# ---------- 核心撮合 ----------
def _apply_fill(
    session: Session,
    order: Order,
    fill_price: float,
) -> None:
    """成交后更新账户、持仓、订单、流水。调用前需自行保证资金/持仓充足。"""
    acc = session.exec(select(Account).where(Account.id == 1)).first()
    pos = session.exec(select(Position).where(Position.symbol == order.symbol)).first()

    cost = order.quantity * fill_price

    if order.side == "buy":
        acc.cash -= cost
        if pos is None:
            pos = Position(symbol=order.symbol, quantity=order.quantity, avg_price=fill_price)
            session.add(pos)
        else:
            total_qty = pos.quantity + order.quantity
            pos.avg_price = (pos.avg_price * pos.quantity + cost) / total_qty
            pos.quantity = total_qty
            pos.updated_at = datetime.utcnow()
    else:  # sell
        acc.cash += cost
        if pos is None or pos.quantity < order.quantity:
            raise MatchingError("持仓不足")
        pos.quantity -= order.quantity
        pos.updated_at = datetime.utcnow()
        # 数量归零后保留行但 quantity=0，不清均价（历史参考）

    order.status = "filled"
    order.filled_price = fill_price
    order.filled_at = datetime.utcnow()

    trade = Trade(
        order_id=order.id,
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        price=fill_price,
    )
    session.add(trade)
    session.add(acc)
    session.add(order)
    if pos:
        session.add(pos)


async def place_order(
    symbol: str,
    side: str,
    type_: str,
    quantity: float,
    price: Optional[float] = None,
) -> dict:
    """下单入口。返回 order dict。"""
    if type_ == "limit" and price is None:
        raise MatchingError("限价单必须提供 price")

    # 获取当前价（用于市价成交或资金预检）
    ticker = await exchange.get_ticker(symbol)
    last_price = ticker["last"]

    with get_session() as session:
        acc = session.exec(select(Account).where(Account.id == 1)).first()

        order = Order(
            symbol=symbol,
            side=side,
            type=type_,
            quantity=quantity,
            price=price,
            status="open",
        )
        session.add(order)
        session.commit()
        session.refresh(order)

        if type_ == "market":
            # 资金/持仓预检
            if side == "buy" and acc.cash < quantity * last_price:
                order.status = "cancelled"
                session.add(order)
                session.commit()
                raise MatchingError("现金余额不足")
            if side == "sell":
                pos = session.exec(
                    select(Position).where(Position.symbol == symbol)
                ).first()
                if pos is None or pos.quantity < quantity:
                    order.status = "cancelled"
                    session.add(order)
                    session.commit()
                    raise MatchingError("持仓不足")
            _apply_fill(session, order, last_price)
            session.commit()
            session.refresh(order)

        else:  # limit
            # 买入限价需冻结现金（简化：仅做预检，不真正冻结）
            if side == "buy" and acc.cash < quantity * price:
                order.status = "cancelled"
                session.add(order)
                session.commit()
                raise MatchingError("现金余额不足")
            if side == "sell":
                pos = session.exec(
                    select(Position).where(Position.symbol == symbol)
                ).first()
                if pos is None or pos.quantity < quantity:
                    order.status = "cancelled"
                    session.add(order)
                    session.commit()
                    raise MatchingError("持仓不足")

        return _serialize_order(order)


def cancel_order(order_id: int) -> dict:
    with get_session() as session:
        order = session.get(Order, order_id)
        if order is None:
            raise MatchingError("订单不存在")
        if order.status != "open":
            raise MatchingError(f"订单状态不可撤销: {order.status}")
        order.status = "cancelled"
        session.add(order)
        session.commit()
        session.refresh(order)
        return _serialize_order(order)


def list_orders(status: Optional[str] = None, limit: int = 200) -> list[dict]:
    with get_session() as session:
        stmt = select(Order).order_by(Order.id.desc()).limit(limit)
        if status:
            stmt = select(Order).where(Order.status == status).order_by(Order.id.desc()).limit(limit)
        orders = session.exec(stmt).all()
        return [_serialize_order(o) for o in orders]


def list_trades(limit: int = 200) -> list[dict]:
    with get_session() as session:
        trades = session.exec(
            select(Trade).order_by(Trade.id.desc()).limit(limit)
        ).all()
        return [
            {
                "id": t.id,
                "order_id": t.order_id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "created_at": t.created_at.isoformat(),
            }
            for t in trades
        ]


def _serialize_order(o: Order) -> dict:
    return {
        "id": o.id,
        "symbol": o.symbol,
        "side": o.side,
        "type": o.type,
        "quantity": o.quantity,
        "price": o.price,
        "status": o.status,
        "filled_price": o.filled_price,
        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
        "created_at": o.created_at.isoformat(),
    }


# ---------- 后台轮询：限价单撮合 ----------
async def limit_order_worker(interval_sec: float = 2.0):
    """后台循环：扫描 open 限价单，按当前价判定成交。"""
    while True:
        try:
            await _scan_and_fill_once()
        except Exception as e:
            print(f"[matching] worker error: {e}")
        await asyncio.sleep(interval_sec)


async def _scan_and_fill_once() -> None:
    with get_session() as session:
        open_limits = session.exec(
            select(Order).where(Order.status == "open", Order.type == "limit")
        ).all()

    if not open_limits:
        return

    # 去重拉价
    symbols = {o.symbol for o in open_limits}
    prices: dict[str, float] = {}
    for sym in symbols:
        try:
            t = await exchange.get_ticker(sym)
            prices[sym] = t["last"]
        except Exception:
            continue

    with get_session() as session:
        for o in open_limits:
            last = prices.get(o.symbol)
            if last is None:
                continue
            # fetch fresh row
            order = session.get(Order, o.id)
            if order is None or order.status != "open":
                continue

            should_fill = (
                (order.side == "buy" and last <= order.price) or
                (order.side == "sell" and last >= order.price)
            )
            if not should_fill:
                continue

            try:
                # 成交前再校验一次资金/持仓
                acc = session.exec(select(Account).where(Account.id == 1)).first()
                if order.side == "buy" and acc.cash < order.quantity * order.price:
                    order.status = "cancelled"
                    session.add(order)
                    continue
                if order.side == "sell":
                    pos = session.exec(
                        select(Position).where(Position.symbol == order.symbol)
                    ).first()
                    if pos is None or pos.quantity < order.quantity:
                        order.status = "cancelled"
                        session.add(order)
                        continue
                _apply_fill(session, order, order.price)
            except Exception as e:
                print(f"[matching] fill error order#{order.id}: {e}")
        session.commit()
