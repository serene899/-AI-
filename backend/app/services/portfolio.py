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
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.core.time import iso_cn, now_cn
from app.models.db import Account, EquitySnapshot, Position, get_session
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



# =============================================================================
# 资产净值快照（Equity Curve）
# =============================================================================
# 每分钟把 total_equity / cash / position_value / unrealized_pnl 写一条到
# EquitySnapshot，前端据此画"资产随时间变化"折线图（类比 Apple Stocks）。
#
# 设计：
# - 60s 间隔写一次；值与上一条完全一致时不写（避免账户空转时的冗余数据）
# - 失败不抛，只打印日志；worker 永远不会把自己搞挂
# - 按 range 查询时做降采样，避免前端一次拿几万个点

_SNAPSHOT_INTERVAL_SEC = 60
_SNAPSHOT_DEDUPE_EPS = 1e-4  # 总资产变化不到 0.0001 认为无变化，不写


async def _write_equity_snapshot_once() -> bool:
    """
    写一条快照。返回是否实际写入（用于调试）。
    值与上一条几乎一致时跳过，减少 DB 行数。
    """
    try:
        snapshot = await build_account_snapshot()
    except Exception as e:
        print(f"[equity] build snapshot failed: {e}")
        return False

    total_equity = float(snapshot["total_equity"])
    cash = float(snapshot["cash"])
    position_value = float(snapshot["position_market_value"])
    unrealized = float(snapshot["unrealized_pnl"])

    try:
        with get_session() as session:
            last = session.exec(
                select(EquitySnapshot).order_by(EquitySnapshot.id.desc()).limit(1)
            ).first()
            if (
                last is not None
                and abs(last.total_equity - total_equity) < _SNAPSHOT_DEDUPE_EPS
                and abs(last.cash - cash) < _SNAPSHOT_DEDUPE_EPS
                and abs(last.position_value - position_value) < _SNAPSHOT_DEDUPE_EPS
            ):
                return False
            row = EquitySnapshot(
                ts=now_cn(),
                total_equity=total_equity,
                cash=cash,
                position_value=position_value,
                unrealized_pnl=unrealized,
            )
            session.add(row)
            session.commit()
            return True
    except Exception as e:
        print(f"[equity] persist snapshot failed: {e}")
        return False


async def equity_snapshot_worker(interval_sec: int = _SNAPSHOT_INTERVAL_SEC) -> None:
    """
    后台循环：每 interval_sec 秒写一次快照。
    main.py 的 startup 里 asyncio.create_task 拉起。
    """
    # 启动后立即写一条，避免首屏图表为空
    await _write_equity_snapshot_once()
    while True:
        await asyncio.sleep(interval_sec)
        try:
            await _write_equity_snapshot_once()
        except Exception as e:
            print(f"[equity] worker iteration error: {e}")


# ----- 查询 -----

def _range_to_window(range_: str) -> tuple[Optional[timedelta], int]:
    """
    把前端传的 range 翻译为 (时间窗口, 期望点数上限)。
    点数上限决定了降采样粒度，让前端拿到的点数稳定在 ~200-1500 之间。
    None 表示不限时间（ALL）。
    """
    r = (range_ or "1D").upper()
    if r == "1H":
        return timedelta(hours=1), 60       # 每分钟一个点
    if r == "1D":
        return timedelta(days=1), 288       # 约 5 分钟一个点
    if r == "1W":
        return timedelta(days=7), 336       # 约 30 分钟一个点
    if r == "1M":
        return timedelta(days=30), 720      # 约 1 小时一个点
    if r == "ALL":
        return None, 1000
    # 兜底按 1D
    return timedelta(days=1), 288


def get_equity_curve(range_: str = "1D") -> dict:
    """
    返回折线图用的数据：
    {
      "range": "1D",
      "points": [{"ts": "...", "equity": 10001.23, "cash": ..., "position_value": ...}, ...],
      "first": <第一个点的 equity>,  # 方便前端算涨跌
      "last":  <最后一个点的 equity>,
      "change": last - first,
      "change_pct": (last/first - 1) * 100
    }
    """
    window, max_points = _range_to_window(range_)
    with get_session() as session:
        stmt = select(EquitySnapshot)
        if window is not None:
            since = now_cn() - window
            stmt = stmt.where(EquitySnapshot.ts >= since)
        stmt = stmt.order_by(EquitySnapshot.ts.asc())
        rows = list(session.exec(stmt).all())

    # 降采样：只在点数超过上限时等距抽取
    if len(rows) > max_points:
        step = len(rows) / max_points
        picked = []
        i = 0.0
        while int(i) < len(rows):
            picked.append(rows[int(i)])
            i += step
        # 保证最后一个点一定包含（用户最关心"当前"）
        if picked[-1].id != rows[-1].id:
            picked.append(rows[-1])
        rows = picked

    points = [
        {
            "ts": iso_cn(r.ts),
            "equity": r.total_equity,
            "cash": r.cash,
            "position_value": r.position_value,
            "unrealized_pnl": r.unrealized_pnl,
        }
        for r in rows
    ]

    if points:
        first = points[0]["equity"]
        last = points[-1]["equity"]
        change = last - first
        change_pct = ((last / first - 1) * 100) if first else 0.0
    else:
        first = last = change = change_pct = 0.0

    return {
        "range": range_.upper(),
        "points": points,
        "first": first,
        "last": last,
        "change": change,
        "change_pct": change_pct,
    }
