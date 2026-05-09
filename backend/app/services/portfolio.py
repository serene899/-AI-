"""账户 / 持仓 / 盈亏计算。"""
from sqlmodel import Session, select

from app.models.db import Account, Position, get_session
from app.services import exchange


def get_account_row(session: Session) -> Account:
    acc = session.exec(select(Account).where(Account.id == 1)).first()
    if acc is None:
        raise RuntimeError("Account not initialized")
    return acc


def get_positions(session: Session) -> list[Position]:
    return list(session.exec(select(Position).where(Position.quantity > 0)).all())


async def build_account_snapshot() -> dict:
    """汇总账户 + 持仓 + 实时盈亏。"""
    with get_session() as session:
        acc = get_account_row(session)
        positions = get_positions(session)

    # 拉取实时价
    position_view = []
    position_market_value = 0.0
    total_cost = 0.0
    total_unrealized = 0.0

    for p in positions:
        try:
            ticker = await exchange.get_ticker(p.symbol)
            last = ticker["last"]
        except Exception:
            last = p.avg_price  # 取不到行情时回退

        market_value = p.quantity * last
        cost = p.quantity * p.avg_price
        unrealized = market_value - cost
        pnl_pct = ((last - p.avg_price) / p.avg_price * 100) if p.avg_price else 0.0

        position_market_value += market_value
        total_cost += cost
        total_unrealized += unrealized

        position_view.append({
            "symbol": p.symbol,
            "quantity": p.quantity,
            "avg_price": p.avg_price,
            "last_price": last,
            "market_value": market_value,
            "unrealized_pnl": unrealized,
            "pnl_pct": pnl_pct,
        })

    total_equity = acc.cash + position_market_value
    total_pnl = total_equity - acc.initial_capital
    total_pnl_pct = (total_pnl / acc.initial_capital * 100) if acc.initial_capital else 0.0

    return {
        "cash": acc.cash,
        "initial_capital": acc.initial_capital,
        "position_market_value": position_market_value,
        "total_equity": total_equity,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "unrealized_pnl": total_unrealized,
        "positions": position_view,
    }
