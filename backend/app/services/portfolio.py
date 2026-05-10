"""
账户 / 持仓 / 盈亏计算。

核心概念（v2 修复）：
    买入 ≠ 亏损。买入只是资产转换（现金→币），持仓未卖出前不产生已实现盈亏。
    - 未实现盈亏 (unrealized) = (现价 - 均价) × 持仓数量
    - 已实现盈亏 (realized)   = 所有卖出成交产生的 (卖出价 - 均价) × 数量 之和
    - 总盈亏                  = 未实现 + 已实现 = total_equity - initial_capital

    策略（机器人）的"策略盈亏"定义为该策略下的：
        (已卖出收回的 USDT) + (剩余持仓按现价估值) - (已花费的 USDT)
    这样：
      · 刚买入还没卖，策略盈亏 ≈ 0（币价不动时）
      · 币涨了没卖，策略盈亏 = 浮动盈利
      · 低买高卖完成一轮，策略盈亏 = 实际赚到的 USDT
"""
import asyncio

from sqlmodel import Session, select

from app.models.db import Account, Position, Trade, get_session
from app.services import exchange


def get_account_row(session: Session) -> Account:
    acc = session.exec(select(Account).where(Account.id == 1)).first()
    if acc is None:
        raise RuntimeError("Account not initialized")
    return acc


def get_positions(session: Session) -> list[Position]:
    return list(session.exec(select(Position).where(Position.quantity > 0)).all())


async def _safe_last_price(symbol: str, fallback: float) -> float:
    """拿最新价；拿不到就回退到 fallback（通常是 avg_price），不抛给调用方。"""
    try:
        ticker = await exchange.get_ticker(symbol)
        return ticker["last"]
    except Exception:
        return fallback


async def build_account_snapshot() -> dict:
    """
    汇总账户 + 持仓 + 实时盈亏。
    并发拉取各 symbol 的 ticker，避免串行等待导致前端 15s 超时。
    """
    with get_session() as session:
        acc = get_account_row(session)
        positions = get_positions(session)

    if positions:
        prices = await asyncio.gather(
            *[_safe_last_price(p.symbol, p.avg_price) for p in positions]
        )
    else:
        prices = []

    position_view = []
    position_market_value = 0.0
    total_unrealized = 0.0

    for p, last in zip(positions, prices):
        market_value = p.quantity * last
        cost_basis = p.quantity * p.avg_price
        unrealized = market_value - cost_basis
        pnl_pct = ((last - p.avg_price) / p.avg_price * 100) if p.avg_price else 0.0

        position_market_value += market_value
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
