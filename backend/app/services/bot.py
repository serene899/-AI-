"""
自动交易机器人管理器 v2.0。

三大策略（全部参数统一以 USDT 计价）:
- DCA  (定投):   每 interval_sec 秒市价买入 amount_usdt 美元
- GRID (网格):   跌 drop_pct 自动买入 amount_usdt / 涨 rise_pct 自动卖出等量持仓
- MA   (双均线):  MA_short 上穿 MA_long 金叉买入 amount_usdt；下穿死叉卖出等量持仓

核心特性:
- Hot-reload: 运行中可热更新参数，当前 sleep 被立即中断，新参数下一轮生效
- Status 机器:      initializing -> running -> error -> stopped
- 熔断:             连续 MAX_ERRORS 次错误自动停机
- 所有下单均通过 matching.place_order() 统一走撮合/账户逻辑
"""
import asyncio
import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.services import exchange
from app.services import matching


MAX_CONSECUTIVE_ERRORS = 5
MAX_LOG_ENTRIES = 200


# =============================================================================
# 策略元信息（前端拿去动态生成表单）
# =============================================================================
STRATEGY_DEFS = [
    {
        "key": "dca",
        "name": "定投 DCA",
        "description": "每隔固定时间按市价买入固定金额，简单稳健，适合长线",
        "fields": [
            {"name": "amount_usdt", "label": "每次买入金额 (USDT)", "type": "number",
             "default": 100, "min": 1, "hot": True},
            {"name": "interval_sec", "label": "间隔时间 (秒)", "type": "number",
             "default": 60, "min": 5, "hot": True},
        ],
    },
    {
        "key": "grid",
        "name": "智能网格",
        "description": "跌 X% 买入、涨 Y% 卖出；高抛低吸，适合震荡行情",
        "fields": [
            {"name": "amount_usdt", "label": "每次交易金额 (USDT)", "type": "number",
             "default": 100, "min": 1, "hot": True},
            {"name": "drop_pct", "label": "跌幅触发买入 (%)", "type": "number",
             "default": 1.0, "min": 0.1, "max": 50, "hot": True},
            {"name": "rise_pct", "label": "涨幅触发卖出 (%)", "type": "number",
             "default": 1.0, "min": 0.1, "max": 50, "hot": True},
            {"name": "poll_sec", "label": "轮询间隔 (秒)", "type": "number",
             "default": 3, "min": 1, "hot": True},
        ],
    },
    {
        "key": "ma",
        "name": "双均线 MA",
        "description": "短期均线上穿长期均线金叉买入；下穿死叉卖出持仓。经典趋势策略",
        "fields": [
            {"name": "amount_usdt", "label": "每次交易金额 (USDT)", "type": "number",
             "default": 200, "min": 1, "hot": True},
            {"name": "ma_short", "label": "短期均线周期", "type": "number",
             "default": 5, "min": 2, "max": 50, "hot": True},
            {"name": "ma_long", "label": "长期均线周期", "type": "number",
             "default": 20, "min": 3, "max": 200, "hot": True},
            {"name": "kline_interval", "label": "K 线周期", "type": "select",
             "options": ["1m", "5m", "15m", "1h", "4h", "1d"],
             "default": "1m", "hot": True},
            {"name": "poll_sec", "label": "轮询间隔 (秒)", "type": "number",
             "default": 10, "min": 3, "hot": True},
        ],
    },
]

STRATEGY_KEYS = {s["key"] for s in STRATEGY_DEFS}


# =============================================================================
# 数据模型
# =============================================================================
@dataclass
class BotLogEntry:
    ts: float
    level: str        # info | trade | error
    message: str


@dataclass
class BotRunner:
    id: int
    strategy: str
    symbol: str
    params: dict
    # 运行状态机: initializing -> running -> error -> stopped
    status: str = "initializing"
    running: bool = True
    started_at: float = field(default_factory=time.time)
    stopped_at: Optional[float] = None
    last_error: Optional[str] = None
    last_error_ts: Optional[float] = None
    consecutive_errors: int = 0

    stats: dict = field(default_factory=lambda: {
        "trades": 0, "buys": 0, "sells": 0,
        "total_buy_qty": 0.0, "total_sell_qty": 0.0,
        "total_spent": 0.0, "total_received": 0.0,
        "last_price": None,
        "reference_price": None,  # grid 用
        "ma_short": None, "ma_long": None,  # ma 用
        "win_count": 0, "loss_count": 0,    # 胜率统计
    })
    logs: list = field(default_factory=list)
    task: Optional[asyncio.Task] = None

    # ★ 热更新信号：params 变更时 set()，策略循环的 interruptible_sleep 会被唤醒
    _params_changed: asyncio.Event = field(default_factory=asyncio.Event)

    def log(self, level: str, message: str) -> None:
        entry = BotLogEntry(ts=time.time(), level=level, message=message)
        self.logs.append(entry)
        if len(self.logs) > MAX_LOG_ENTRIES:
            self.logs = self.logs[-MAX_LOG_ENTRIES:]

    def record_error(self, err: str) -> bool:
        """记录错误，返回是否应触发熔断停机。"""
        self.last_error = err
        self.last_error_ts = time.time()
        self.consecutive_errors += 1
        self.log("error", err)
        if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self.status = "error"
            return True
        # 短暂挂红一下，下一轮成功会变回 running
        self.status = "error"
        return False

    def record_success(self) -> None:
        self.consecutive_errors = 0
        if self.status != "stopped":
            self.status = "running"

    def to_dict(self, logs_since_ts: float = 0.0) -> dict:
        logs = [l for l in self.logs if l.ts > logs_since_ts]
        if logs_since_ts == 0.0:
            logs = logs[-50:]  # 初次加载只给最近 50 条
        return {
            "id": self.id,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "params": self.params,
            "status": self.status,
            "running": self.running,
            "started_at": datetime.fromtimestamp(self.started_at).isoformat(),
            "stopped_at": (
                datetime.fromtimestamp(self.stopped_at).isoformat()
                if self.stopped_at else None
            ),
            "last_error": self.last_error,
            "last_error_ts": (
                datetime.fromtimestamp(self.last_error_ts).isoformat()
                if self.last_error_ts else None
            ),
            "consecutive_errors": self.consecutive_errors,
            "stats": self.stats,
            "logs": [
                {
                    "ts": datetime.fromtimestamp(l.ts).isoformat(),
                    "ts_epoch": l.ts,
                    "level": l.level,
                    "message": l.message,
                }
                for l in logs
            ],
        }


# =============================================================================
# Manager
# =============================================================================
class BotManager:
    def __init__(self) -> None:
        self._id_seq = itertools.count(1)
        self._bots: dict[int, BotRunner] = {}

    # -------- Query ----------
    def list(self) -> list:
        items = sorted(
            self._bots.values(),
            key=lambda b: (b.status == "stopped", -b.started_at),
        )
        return [b.to_dict() for b in items]

    def get(self, bot_id: int, logs_since_ts: float = 0.0) -> Optional[dict]:
        b = self._bots.get(bot_id)
        return b.to_dict(logs_since_ts=logs_since_ts) if b else None

    def get_logs(self, bot_id: int, since_ts: float = 0.0) -> list:
        b = self._bots.get(bot_id)
        if b is None:
            return []
        return [
            {
                "ts": datetime.fromtimestamp(l.ts).isoformat(),
                "ts_epoch": l.ts,
                "level": l.level,
                "message": l.message,
            }
            for l in b.logs if l.ts > since_ts
        ]

    # -------- Start ----------
    async def start(self, strategy: str, symbol: str, params: dict) -> dict:
        strategy = strategy.lower()
        if strategy not in STRATEGY_KEYS:
            raise ValueError(f"不支持的策略: {strategy}")

        params = self._validate(strategy, params)

        for b in self._bots.values():
            if b.running and b.symbol == symbol and b.strategy == strategy:
                raise ValueError(
                    f"已有一个运行中的 {strategy.upper()} 机器人在交易 {symbol}，请先停止它"
                )

        bot_id = next(self._id_seq)
        runner = BotRunner(id=bot_id, strategy=strategy, symbol=symbol, params=params)
        runner.log(
            "info",
            f"机器人启动 · 策略={strategy.upper()} · {symbol} · 参数={params}"
        )
        self._bots[bot_id] = runner

        runner.task = asyncio.create_task(self._run(runner))
        return runner.to_dict()

    # -------- Hot-update params ----------
    def update_params(self, bot_id: int, new_params: dict) -> dict:
        b = self._bots.get(bot_id)
        if b is None:
            raise ValueError("机器人不存在")
        if not b.running:
            raise ValueError("机器人已停止，无法修改参数")

        # 只允许修改 hot=True 的字段
        hot_fields = self._hot_fields(b.strategy)
        filtered = {k: v for k, v in new_params.items() if k in hot_fields}
        if not filtered:
            raise ValueError("没有可热更新的字段")

        merged = {**b.params, **filtered}
        merged = self._validate(b.strategy, merged)  # 复用校验

        changes = []
        for k, v in filtered.items():
            old = b.params.get(k)
            if old != v:
                changes.append(f"{k}: {old} → {v}")
        b.params = merged

        if changes:
            b.log("info", "参数热更新：" + "；".join(changes))
            # ★ 唤醒当前 sleep
            b._params_changed.set()
        return b.to_dict()

    # -------- Stop ----------
    def stop(self, bot_id: int) -> dict:
        b = self._bots.get(bot_id)
        if b is None:
            raise ValueError("机器人不存在")
        if not b.running:
            return b.to_dict()
        b.running = False
        b.stopped_at = time.time()
        b.status = "stopped"
        b.log("info", "收到停止指令")
        # 同时唤醒可能在 sleep 的 task，让它立刻退出
        b._params_changed.set()
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

    # =========================================================================
    # 校验：返回清理后的 params（数值类型统一）
    # =========================================================================
    @staticmethod
    def _hot_fields(strategy: str) -> set:
        for s in STRATEGY_DEFS:
            if s["key"] == strategy:
                return {f["name"] for f in s["fields"] if f.get("hot")}
        return set()

    def _validate(self, strategy: str, p: dict) -> dict:
        if strategy == "dca":
            return self._validate_dca(p)
        if strategy == "grid":
            return self._validate_grid(p)
        if strategy == "ma":
            return self._validate_ma(p)
        raise ValueError(f"未知策略: {strategy}")

    @staticmethod
    def _validate_dca(p: dict) -> dict:
        amount = float(p.get("amount_usdt", 0))
        interval = int(p.get("interval_sec", 0))
        if amount <= 0:
            raise ValueError("每次买入金额 (USDT) 必须 > 0")
        if interval < 5:
            raise ValueError("间隔时间不能小于 5 秒")
        return {"amount_usdt": amount, "interval_sec": interval}

    @staticmethod
    def _validate_grid(p: dict) -> dict:
        amount = float(p.get("amount_usdt", 0))
        drop = float(p.get("drop_pct", 0))
        rise = float(p.get("rise_pct", 0))
        poll = int(p.get("poll_sec", 3))
        if amount <= 0:
            raise ValueError("每次交易金额 (USDT) 必须 > 0")
        if not (0 < drop < 50):
            raise ValueError("跌幅百分比必须在 (0, 50) 之间")
        if not (0 < rise < 50):
            raise ValueError("涨幅百分比必须在 (0, 50) 之间")
        if poll < 1:
            raise ValueError("轮询间隔不能小于 1 秒")
        return {
            "amount_usdt": amount,
            "drop_pct": drop,
            "rise_pct": rise,
            "poll_sec": poll,
        }

    @staticmethod
    def _validate_ma(p: dict) -> dict:
        amount = float(p.get("amount_usdt", 0))
        ma_short = int(p.get("ma_short", 5))
        ma_long = int(p.get("ma_long", 20))
        interval = str(p.get("kline_interval", "1m"))
        poll = int(p.get("poll_sec", 10))
        if amount <= 0:
            raise ValueError("每次交易金额 (USDT) 必须 > 0")
        if ma_short < 2:
            raise ValueError("短期均线周期至少为 2")
        if ma_long <= ma_short:
            raise ValueError("长期均线周期必须大于短期均线周期")
        if interval not in ("1m", "5m", "15m", "1h", "4h", "1d"):
            raise ValueError(f"不支持的 K 线周期: {interval}")
        if poll < 3:
            raise ValueError("轮询间隔不能小于 3 秒")
        return {
            "amount_usdt": amount,
            "ma_short": ma_short,
            "ma_long": ma_long,
            "kline_interval": interval,
            "poll_sec": poll,
        }

    # =========================================================================
    # 运行时：dispatcher
    # =========================================================================
    async def _run(self, b: BotRunner) -> None:
        try:
            if b.strategy == "dca":
                await self._run_dca(b)
            elif b.strategy == "grid":
                await self._run_grid(b)
            elif b.strategy == "ma":
                await self._run_ma(b)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            b.log("error", f"机器人异常退出: {type(e).__name__}: {e}")
            b.status = "error"
        finally:
            b.running = False
            if b.stopped_at is None:
                b.stopped_at = time.time()
            if b.status != "error":
                b.status = "stopped"
            b.log("info", f"机器人已停止运行（最终状态: {b.status}）")

    # -------- helpers ----------
    async def _interruptible_sleep(self, b: BotRunner, seconds: float) -> None:
        """
        可被参数变更 / stop 打断的 sleep。
        如果在此期间 params 变了，立刻返回 —— 这就是 B 方案"立即生效"的核心。
        """
        if seconds <= 0:
            return
        b._params_changed.clear()
        try:
            await asyncio.wait_for(b._params_changed.wait(), timeout=seconds)
            # 被提前唤醒 —— 参数变了或收到停止信号
        except asyncio.TimeoutError:
            pass
        finally:
            b._params_changed.clear()

    async def _startup_probe(self, b: BotRunner) -> Optional[float]:
        """启动探活：取一次 ticker。失败则立刻把机器人标记成 error 并返回 None。"""
        try:
            t = await exchange.get_ticker(b.symbol)
            price = t["last"]
            b.stats["last_price"] = price
            b.status = "running"
            b.consecutive_errors = 0
            b.log("info", f"探活成功，当前 {b.symbol} = {price:.4f}")
            return price
        except Exception as e:
            b.log("error", f"启动探活失败: {type(e).__name__}: {e}")
            b.last_error = f"启动探活失败: {e}"
            b.last_error_ts = time.time()
            b.status = "error"
            b.running = False
            b.stopped_at = time.time()
            return None

    @staticmethod
    def _qty_from_usdt(amount_usdt: float, price: float) -> float:
        """USDT 金额换算为币种数量，保留 8 位精度。"""
        return round(amount_usdt / price, 8) if price > 0 else 0.0

    # =========================================================================
    # 策略 1：DCA
    # =========================================================================
    async def _run_dca(self, b: BotRunner) -> None:
        if await self._startup_probe(b) is None:
            return

        while b.running:
            # ★ 每轮重读参数（hot-reload 的关键）
            amount_usdt = float(b.params["amount_usdt"])
            interval_sec = int(b.params["interval_sec"])

            try:
                ticker = await exchange.get_ticker(b.symbol)
                last = ticker["last"]
                b.stats["last_price"] = last

                qty = self._qty_from_usdt(amount_usdt, last)
                if qty <= 0:
                    b.record_error(f"估算数量过小: {qty}（金额 ${amount_usdt} / 价格 {last}）")
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
                        f"定投买入 {qty} {b.symbol} @ {last:.4f} "
                        f"(花费 ${qty*last:.2f} / 目标 ${amount_usdt:.2f})",
                    )
                    b.record_success()
            except matching.MatchingError as e:
                stopped = b.record_error(f"下单失败：{e}")
                if stopped:
                    b.log("error", "连续错误过多，自动停机。请检查账户资金")
                    b.running = False
                    return
            except exchange.ExchangeError as e:
                b.record_error(f"行情获取失败：{e}")
            except Exception as e:
                b.record_error(f"未知错误：{type(e).__name__}: {e}")

            if not b.running:
                return
            await self._interruptible_sleep(b, interval_sec)

    # =========================================================================
    # 策略 2：Grid
    # =========================================================================
    async def _run_grid(self, b: BotRunner) -> None:
        ref = await self._startup_probe(b)
        if ref is None:
            return
        b.stats["reference_price"] = ref
        b.log("info", f"网格初始参考价 = {ref:.4f}，等待价格波动触发…")

        while b.running:
            # ★ 每轮重读参数
            amount_usdt = float(b.params["amount_usdt"])
            drop_pct = float(b.params["drop_pct"]) / 100.0
            rise_pct = float(b.params["rise_pct"]) / 100.0
            poll_sec = int(b.params["poll_sec"])

            try:
                ticker = await exchange.get_ticker(b.symbol)
                last = ticker["last"]
                b.stats["last_price"] = last

                buy_trigger = ref * (1 - drop_pct)
                sell_trigger = ref * (1 + rise_pct)

                if last <= buy_trigger:
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
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
                            f"⬇ 触发买入：{qty} {b.symbol} @ {last:.4f} "
                            f"(参考 {ref:.4f}, 跌幅 {(ref-last)/ref*100:.2f}%, 花费 ${qty*last:.2f})",
                        )
                        ref = last
                        b.stats["reference_price"] = ref
                        b.record_success()
                    except matching.MatchingError as e:
                        b.record_error(f"买入失败：{e}（参考价重置）")
                        ref = last
                        b.stats["reference_price"] = ref
                elif last >= sell_trigger:
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
                        await matching.place_order(
                            symbol=b.symbol, side="sell", type_="market",
                            quantity=qty, price=None,
                        )
                        b.stats["trades"] += 1
                        b.stats["sells"] += 1
                        b.stats["total_sell_qty"] += qty
                        b.stats["total_received"] += qty * last
                        b.log(
                            "trade",
                            f"⬆ 触发卖出：{qty} {b.symbol} @ {last:.4f} "
                            f"(参考 {ref:.4f}, 涨幅 {(last-ref)/ref*100:.2f}%, 得 ${qty*last:.2f})",
                        )
                        ref = last
                        b.stats["reference_price"] = ref
                        b.record_success()
                    except matching.MatchingError as e:
                        b.record_error(
                            f"卖出失败：{e}（可能持仓不足，参考价已重置）"
                        )
                        ref = last
                        b.stats["reference_price"] = ref
                else:
                    # 行情未触发也算一次"探活成功"，让红色状态回复到绿色
                    b.record_success()
            except exchange.ExchangeError as e:
                stopped = b.record_error(f"行情失败：{e}")
                if stopped:
                    b.running = False
                    return
            except Exception as e:
                b.record_error(f"未知错误：{type(e).__name__}: {e}")

            if not b.running:
                return
            await self._interruptible_sleep(b, poll_sec)

    # =========================================================================
    # 策略 3：MA（双均线）
    # =========================================================================
    async def _run_ma(self, b: BotRunner) -> None:
        if await self._startup_probe(b) is None:
            return

        prev_diff_sign: Optional[int] = None  # 上一轮 short - long 的正负号
        b.log("info", "MA 策略已启动，等待金叉/死叉信号…")

        while b.running:
            # ★ 每轮重读参数
            amount_usdt = float(b.params["amount_usdt"])
            ma_short = int(b.params["ma_short"])
            ma_long = int(b.params["ma_long"])
            kline_interval = str(b.params["kline_interval"])
            poll_sec = int(b.params["poll_sec"])

            try:
                need = max(ma_long + 5, ma_short + 5)
                candles = await exchange.get_kline(b.symbol, kline_interval, min(need, 300))
                if len(candles) < ma_long:
                    b.record_error(
                        f"K 线数据不足：{len(candles)} < {ma_long}，请缩短长周期或换周期"
                    )
                    await self._interruptible_sleep(b, poll_sec)
                    continue

                closes = [c[4] for c in candles]
                last = closes[-1]
                b.stats["last_price"] = last

                s_val = sum(closes[-ma_short:]) / ma_short
                l_val = sum(closes[-ma_long:]) / ma_long
                b.stats["ma_short"] = s_val
                b.stats["ma_long"] = l_val

                diff = s_val - l_val
                cur_sign = 1 if diff > 0 else (-1 if diff < 0 else 0)

                signal = None
                if prev_diff_sign is not None and cur_sign != 0 and prev_diff_sign != cur_sign:
                    signal = "golden" if cur_sign > 0 else "death"

                if signal == "golden":
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
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
                            f"🌟 金叉买入 {qty} {b.symbol} @ {last:.4f} "
                            f"(MA{ma_short}={s_val:.4f} 上穿 MA{ma_long}={l_val:.4f})"
                        )
                        b.record_success()
                    except matching.MatchingError as e:
                        b.record_error(f"金叉买入失败：{e}")
                elif signal == "death":
                    # 卖出量 = 相同 USDT 等价的数量；不足时在 matching 层会报错
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
                        await matching.place_order(
                            symbol=b.symbol, side="sell", type_="market",
                            quantity=qty, price=None,
                        )
                        b.stats["trades"] += 1
                        b.stats["sells"] += 1
                        b.stats["total_sell_qty"] += qty
                        b.stats["total_received"] += qty * last
                        b.log(
                            "trade",
                            f"💀 死叉卖出 {qty} {b.symbol} @ {last:.4f} "
                            f"(MA{ma_short}={s_val:.4f} 下穿 MA{ma_long}={l_val:.4f})"
                        )
                        b.record_success()
                    except matching.MatchingError as e:
                        b.record_error(f"死叉卖出失败（可能持仓不足）：{e}")
                else:
                    b.record_success()

                prev_diff_sign = cur_sign
            except exchange.ExchangeError as e:
                stopped = b.record_error(f"行情失败：{e}")
                if stopped:
                    b.running = False
                    return
            except Exception as e:
                b.record_error(f"未知错误：{type(e).__name__}: {e}")

            if not b.running:
                return
            await self._interruptible_sleep(b, poll_sec)


bot_manager = BotManager()
