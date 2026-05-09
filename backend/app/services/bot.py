"""
自动交易机器人管理器。

支持策略:
- DCA (定投): 每 interval_sec 秒买入 amount_usdt 美元金额
- GRID (智能网格): 跌 drop_pct 自动买入, 涨 rise_pct 自动卖出

Bot 运行时存于内存（BotManager）；服务重启后需重新启动。
所有下单均通过 matching.place_order()，与手动交易共用撮合/账户逻辑。
"""
import asyncio
import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.services import exchange
from app.services import matching


@dataclass
class BotLogEntry:
    ts: float
    level: str       # info | trade | error
    message: str


@dataclass
class BotRunner:
    id: int
    strategy: str
    symbol: str
    params: dict
    running: bool = True
    started_at: float = field(default_factory=time.time)
    stopped_at: Optional[float] = None
    stats: dict = field(default_factory=lambda: {
        "trades": 0, "buys": 0, "sells": 0,
        "total_buy_qty": 0.0, "total_sell_qty": 0.0,
        "total_spent": 0.0, "total_received": 0.0,
        "last_price": None, "reference_price": None,
    })
    logs: list = field(default_factory=list)
    task: Optional[asyncio.Task] = None

    def log(self, level: str, message: str) -> None:
        entry = BotLogEntry(ts=time.time(), level=level, message=message)
        self.logs.append(entry)
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "params": self.params,
            "running": self.running,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat(),
            "stopped_at": (
                datetime.fromtimestamp(self.stopped_at).isoformat()
                if self.stopped_at else None
            ),
            "stats": self.stats,
            "logs": [
                {
                    "ts": datetime.fromtimestamp(l.ts).isoformat(),
                    "level": l.level,
                    "message": l.message,
                }
                for l in self.logs[-20:]
            ],
        }


class BotManager:
    def __init__(self) -> None:
        self._id_seq = itertools.count(1)
        self._bots: dict[int, BotRunner] = {}

    def list(self) -> list:
        items = sorted(
            self._bots.values(),
            key=lambda b: (not b.running, -b.started_at),
        )
        return [b.to_dict() for b in items]

    def get(self, bot_id: int) -> Optional[dict]:
        b = self._bots.get(bot_id)
        return b.to_dict() if b else None

    async def start(self, strategy: str, symbol: str, params: dict) -> dict:
        strategy = strategy.lower()
        if strategy not in ("dca", "grid"):
            raise ValueError(f"不支持的策略: {strategy}")

        if strategy == "dca":
            self._validate_dca(params)
        else:
            self._validate_grid(params)

        for b in self._bots.values():
            if b.running and b.symbol == symbol and b.strategy == strategy:
                raise ValueError(
                    f"已有一个运行中的 {strategy.upper()} 机器人在交易 {symbol}，请先停止它"
                )

        bot_id = next(self._id_seq)
        runner = BotRunner(id=bot_id, strategy=strategy, symbol=symbol, params=params)
        runner.log("info", f"机器人启动 · 策略={strategy.upper()} · {symbol} · 参数={params}")
        self._bots[bot_id] = runner

        if strategy == "dca":
            runner.task = asyncio.create_task(self._run_dca(runner))
        else:
            runner.task = asyncio.create_task(self._run_grid(runner))
        return runner.to_dict()

    def stop(self, bot_id: int) -> dict:
        b = self._bots.get(bot_id)
        if b is None:
            raise ValueError("机器人不存在")
        if not b.running:
            return b.to_dict()
        b.running = False
        b.stopped_at = time.time()
        b.log("info", "收到停止指令，已终止运行")
        if b.task and not b.task.done():
            b.task.cancel()
        return b.to_dict()

    def stop_all(self) -> None:
        for b in list(self._bots.values()):
            if b.running:
                try:
                    self.stop(b.id)
                except Exception:
                    pass

    @staticmethod
    def _validate_dca(p: dict) -> None:
        required = ["amount_usdt", "interval_sec"]
        for k in required:
            if k not in p:
                raise ValueError(f"DCA 缺少参数: {k}")
        if p["amount_usdt"] <= 0:
            raise ValueError("amount_usdt 必须 > 0")
        if p["interval_sec"] < 5:
            raise ValueError("interval_sec 不能小于 5 秒")

    @staticmethod
    def _validate_grid(p: dict) -> None:
        required = ["quantity", "drop_pct", "rise_pct"]
        for k in required:
            if k not in p:
                raise ValueError(f"GRID 缺少参数: {k}")
        if p["quantity"] <= 0:
            raise ValueError("quantity 必须 > 0")
        if not (0 < p["drop_pct"] < 50):
            raise ValueError("drop_pct 必须在 (0, 50) 之间")
        if not (0 < p["rise_pct"] < 50):
            raise ValueError("rise_pct 必须在 (0, 50) 之间")

    async def _run_dca(self, b: BotRunner) -> None:
        amount = float(b.params["amount_usdt"])
        interval = int(b.params["interval_sec"])

        try:
            while b.running:
                try:
                    ticker = await exchange.get_ticker(b.symbol)
                    last = ticker["last"]
                    b.stats["last_price"] = last
                    qty = round(amount / last, 8)
                    if qty <= 0:
                        b.log("error", f"估算数量过小: {qty}")
                    else:
                        await matching.place_order(
                            symbol=b.symbol, side="buy", type_="market",
                            quantity=qty, price=None,
                        )
                        b.stats["trades"] += 1
                        b.stats["buys"] += 1
                        b.stats["total_buy_qty"] += qty
                        b.stats["total_spent"] += qty * last
                        b.log(
                            "trade",
                            f"定投买入 {qty} {b.symbol} @ {last:.4f} (约 ${qty*last:.2f})",
                        )
                except matching.MatchingError as e:
                    b.log("error", f"下单失败: {e}")
                except exchange.ExchangeError as e:
                    b.log("error", f"行情获取失败: {e}")
                except Exception as e:
                    b.log("error", f"未知错误: {e}")

                for _ in range(interval):
                    if not b.running:
                        return
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            b.running = False
            if b.stopped_at is None:
                b.stopped_at = time.time()
            b.log("info", "DCA 机器人已停止")

    async def _run_grid(self, b: BotRunner) -> None:
        quantity = float(b.params["quantity"])
        drop_pct = float(b.params["drop_pct"]) / 100.0
        rise_pct = float(b.params["rise_pct"]) / 100.0
        poll_sec = int(b.params.get("poll_sec", 3))

        try:
            init_ticker = await exchange.get_ticker(b.symbol)
            ref = init_ticker["last"]
            b.stats["reference_price"] = ref
            b.stats["last_price"] = ref
            b.log("info", f"初始参考价 = {ref:.4f}，等待触发 ...")

            while b.running:
                try:
                    ticker = await exchange.get_ticker(b.symbol)
                    last = ticker["last"]
                    b.stats["last_price"] = last

                    buy_trigger = ref * (1 - drop_pct)
                    sell_trigger = ref * (1 + rise_pct)

                    if last <= buy_trigger:
                        try:
                            await matching.place_order(
                                symbol=b.symbol, side="buy", type_="market",
                                quantity=quantity, price=None,
                            )
                            b.stats["trades"] += 1
                            b.stats["buys"] += 1
                            b.stats["total_buy_qty"] += quantity
                            b.stats["total_spent"] += quantity * last
                            b.log(
                                "trade",
                                f"跌破触发 买入 {quantity} {b.symbol} @ {last:.4f} "
                                f"(参考 {ref:.4f}, 跌幅 {(ref-last)/ref*100:.2f}%)",
                            )
                            ref = last
                            b.stats["reference_price"] = ref
                        except matching.MatchingError as e:
                            b.log("error", f"买入失败: {e}")
                            ref = last
                            b.stats["reference_price"] = ref
                    elif last >= sell_trigger:
                        try:
                            await matching.place_order(
                                symbol=b.symbol, side="sell", type_="market",
                                quantity=quantity, price=None,
                            )
                            b.stats["trades"] += 1
                            b.stats["sells"] += 1
                            b.stats["total_sell_qty"] += quantity
                            b.stats["total_received"] += quantity * last
                            b.log(
                                "trade",
                                f"涨破触发 卖出 {quantity} {b.symbol} @ {last:.4f} "
                                f"(参考 {ref:.4f}, 涨幅 {(last-ref)/ref*100:.2f}%)",
                            )
                            ref = last
                            b.stats["reference_price"] = ref
                        except matching.MatchingError as e:
                            b.log("error", f"卖出失败（可能持仓不足）: {e}")
                            ref = last
                            b.stats["reference_price"] = ref
                except exchange.ExchangeError as e:
                    b.log("error", f"行情失败: {e}")
                except Exception as e:
                    b.log("error", f"未知错误: {e}")

                for _ in range(poll_sec):
                    if not b.running:
                        return
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            b.running = False
            if b.stopped_at is None:
                b.stopped_at = time.time()
            b.log("info", "网格机器人已停止")


bot_manager = BotManager()
