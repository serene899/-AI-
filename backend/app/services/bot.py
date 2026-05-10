"""
自动交易机器人管理器 v3.0 — SQLite-backed hot reload。

关键设计：
    ┌───────────────────────────────────────────────┐
    │  SQLite (BotConfig table)  ← 配置的唯一真源     │
    │  ├── params_json (JSON 字符串)                 │
    │  └── status / last_error / timestamps          │
    └───────────────────────────────────────────────┘
              ▲                           ▲
              │ 每轮 SELECT 读最新参数      │ PATCH /bot/{id}/params 写
              │                           │
    ┌────────────────────┐        ┌──────────────┐
    │ 策略循环 (asyncio) │        │ 前端编辑按钮 │
    └────────────────────┘        └──────────────┘

三大策略（全部以 USDT 为输入单位，1 USDT 起步）:
- DCA  (定投):     每 interval_sec 秒市价买入 amount_usdt 美元
- GRID (网格):     跌 drop_pct 买入 amount_usdt；涨 rise_pct 卖等量
- MA   (双均线):   短均线上穿长均线金叉买入；下穿死叉卖出

热编辑流程：
    1. 用户 PATCH 参数 → 写 SQLite → 触发 asyncio.Event 唤醒 sleep
    2. 策略下一轮 while 开头 → SELECT 从 DB 拿最新 params → 按新值执行
    3. 机器人不停、不重启、下一轮立即按新参数跑
"""
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlmodel import select

from app.core.time import iso_cn, now_cn, ts_to_cn_iso
from app.models.db import BotConfig, get_session
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
        "name": "定投策略",
        "description": "每隔固定时间按市价买入固定金额，简单稳健，适合长线",
        "fields": [
            {"name": "amount_usdt", "label": "单次投入金额 (USDT)", "type": "number",
             "default": 100, "min": 1, "hot": True},
            {"name": "interval_sec", "label": "定投间隔 (秒)", "type": "number",
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
        "name": "双均线策略",
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
# 运行时数据（只放"不该持久化"的东西：任务句柄、日志环、唤醒事件、统计）
# =============================================================================
@dataclass
class BotLogEntry:
    ts: float
    level: str        # info | trade | error
    message: str


@dataclass
class BotRuntime:
    """伴随一个 BotConfig 行的运行时状态，不落盘。"""
    config_id: int
    running: bool = True
    consecutive_errors: int = 0

    stats: dict = field(default_factory=lambda: {
        "trades": 0, "buys": 0, "sells": 0,
        "total_buy_qty": 0.0, "total_sell_qty": 0.0,
        "total_spent": 0.0, "total_received": 0.0,
        "last_price": None,
        "reference_price": None,  # grid 用
        "ma_short": None, "ma_long": None,  # ma 用
    })
    logs: list = field(default_factory=list)
    task: Optional[asyncio.Task] = None

    # ★ 热更新信号：params 变更时 set()，策略循环的 interruptible_sleep 被唤醒
    params_changed: asyncio.Event = field(default_factory=asyncio.Event)

    def log(self, level: str, message: str) -> None:
        entry = BotLogEntry(ts=time.time(), level=level, message=message)
        self.logs.append(entry)
        if len(self.logs) > MAX_LOG_ENTRIES:
            self.logs = self.logs[-MAX_LOG_ENTRIES:]


# =============================================================================
# 数据库访问层（全部放一起，方便定位）
# =============================================================================
def _config_to_dict(cfg: BotConfig, runtime: Optional[BotRuntime] = None,
                    logs_since_ts: float = 0.0) -> dict:
    """把 DB 行 + runtime 合并成前端用的 dict。"""
    try:
        params = json.loads(cfg.params_json)
    except Exception:
        params = {}
    logs: list = []
    if runtime:
        logs_src = [l for l in runtime.logs if l.ts > logs_since_ts]
        if logs_since_ts == 0.0:
            logs_src = logs_src[-50:]
        logs = [
            {
                "ts": ts_to_cn_iso(l.ts),
                "ts_epoch": l.ts,
                "level": l.level,
                "message": l.message,
            }
            for l in logs_src
        ]
    return {
        "id": cfg.id,
        "strategy": cfg.strategy,
        "symbol": cfg.symbol,
        "params": params,
        "status": cfg.status,
        "running": cfg.status not in ("stopped", "error") and (runtime.running if runtime else False),
        "started_at": iso_cn(cfg.started_at),
        "stopped_at": iso_cn(cfg.stopped_at),
        "last_error": cfg.last_error,
        "last_error_ts": iso_cn(cfg.updated_at) if cfg.last_error else None,
        "consecutive_errors": runtime.consecutive_errors if runtime else 0,
        "stats": runtime.stats if runtime else {},
        "logs": logs,
    }


def _db_insert(strategy: str, symbol: str, params: dict) -> BotConfig:
    with get_session() as session:
        cfg = BotConfig(
            strategy=strategy,
            symbol=symbol,
            params_json=json.dumps(params),
            status="initializing",
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return cfg


def _db_read_params(config_id: int) -> Optional[dict]:
    """★ 每轮循环都走这里读最新参数。"""
    with get_session() as session:
        cfg = session.get(BotConfig, config_id)
        if cfg is None:
            return None
        try:
            return json.loads(cfg.params_json)
        except Exception:
            return None


def _db_update_params(config_id: int, new_params: dict) -> Optional[BotConfig]:
    with get_session() as session:
        cfg = session.get(BotConfig, config_id)
        if cfg is None:
            return None
        cfg.params_json = json.dumps(new_params)
        cfg.updated_at = now_cn()
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return cfg


def _db_update_status(config_id: int, status: str,
                      last_error: Optional[str] = None,
                      mark_stopped: bool = False) -> None:
    with get_session() as session:
        cfg = session.get(BotConfig, config_id)
        if cfg is None:
            return
        cfg.status = status
        if last_error is not None:
            cfg.last_error = last_error
        if mark_stopped and cfg.stopped_at is None:
            cfg.stopped_at = now_cn()
        cfg.updated_at = now_cn()
        session.add(cfg)
        session.commit()


def _db_get(config_id: int) -> Optional[BotConfig]:
    with get_session() as session:
        return session.get(BotConfig, config_id)


def _db_list_all() -> list:
    with get_session() as session:
        return list(session.exec(select(BotConfig).order_by(BotConfig.id.desc())).all())


def _db_list_active() -> list:
    """启动时用：找到数据库里还是 running/initializing 状态的配置行。"""
    with get_session() as session:
        stmt = select(BotConfig).where(
            BotConfig.status.in_(["running", "initializing"])
        )
        return list(session.exec(stmt).all())


# =============================================================================
# Manager
# =============================================================================
class BotManager:
    def __init__(self) -> None:
        self._runtimes: dict[int, BotRuntime] = {}

    # -------- Query ----------
    def list(self) -> list:
        rows = _db_list_all()
        return [
            _config_to_dict(cfg, self._runtimes.get(cfg.id))
            for cfg in rows
        ]

    def get(self, bot_id: int, logs_since_ts: float = 0.0) -> Optional[dict]:
        cfg = _db_get(bot_id)
        if cfg is None:
            return None
        return _config_to_dict(cfg, self._runtimes.get(bot_id), logs_since_ts=logs_since_ts)

    def get_logs(self, bot_id: int, since_ts: float = 0.0) -> list:
        rt = self._runtimes.get(bot_id)
        if rt is None:
            return []
        return [
            {
                "ts": ts_to_cn_iso(l.ts),
                "ts_epoch": l.ts,
                "level": l.level,
                "message": l.message,
            }
            for l in rt.logs if l.ts > since_ts
        ]

    # -------- Resume on startup ----------
    async def resume_from_db(self) -> int:
        """
        服务启动时调用：把数据库里 status ∈ {running, initializing} 的机器人重新拉起。
        这就是"重启/刷新不丢机器人"的核心。
        """
        active = _db_list_active()
        if not active:
            return 0
        count = 0
        for cfg in active:
            # 跳过已经拉起过的（正常不会走到，但防御一下）
            if cfg.id in self._runtimes:
                continue
            rt = BotRuntime(config_id=cfg.id)
            rt.log("info",
                   f"🔄 服务启动时从数据库恢复 · 策略={cfg.strategy.upper()} · {cfg.symbol}")
            self._runtimes[cfg.id] = rt
            rt.task = asyncio.create_task(self._run(cfg.id))
            count += 1
        return count

    def cancel_tasks_preserve_status(self) -> None:
        """
        服务优雅关闭时调用：只 cancel 异步任务，不改 DB 状态。
        这样下次启动时 status 还是 running，能被 resume_from_db 拉起来。
        （用户主动点"停止"才调 stop() 把 DB 写成 stopped）
        """
        for rt in self._runtimes.values():
            if rt.task and not rt.task.done():
                rt.task.cancel()

    # -------- Start ----------
    async def start(self, strategy: str, symbol: str, params: dict) -> dict:
        strategy = strategy.lower()
        if strategy not in STRATEGY_KEYS:
            raise ValueError(f"不支持的策略: {strategy}")

        params = self._validate(strategy, params)

        # 防重复：同一 (strategy, symbol) 只能有一个活着的
        for cfg in _db_list_active():
            if cfg.strategy == strategy and cfg.symbol == symbol and cfg.id in self._runtimes:
                rt = self._runtimes.get(cfg.id)
                if rt and rt.running:
                    raise ValueError(
                        f"已有一个运行中的【{strategy.upper()}】机器人在交易 {symbol}，请先停止它"
                    )

        # 1) 写 DB 建配置
        cfg = _db_insert(strategy, symbol, params)
        # 2) 建运行时
        runtime = BotRuntime(config_id=cfg.id)
        runtime.log(
            "info",
            f"机器人启动 · 策略={strategy.upper()} · {symbol} · 参数={params}（配置已落盘）"
        )
        self._runtimes[cfg.id] = runtime
        # 3) 拉起 task
        runtime.task = asyncio.create_task(self._run(cfg.id))
        return _config_to_dict(_db_get(cfg.id), runtime)

    # -------- Hot-update params ----------
    def update_params(self, bot_id: int, new_params: dict) -> dict:
        cfg = _db_get(bot_id)
        if cfg is None:
            raise ValueError("机器人不存在")
        rt = self._runtimes.get(bot_id)
        if not rt or not rt.running or cfg.status == "stopped":
            raise ValueError("机器人已停止，无法修改参数")

        hot_fields = self._hot_fields(cfg.strategy)
        filtered = {k: v for k, v in new_params.items() if k in hot_fields}
        if not filtered:
            raise ValueError("没有可热编辑的字段")

        current = json.loads(cfg.params_json)
        merged = {**current, **filtered}
        merged = self._validate(cfg.strategy, merged)

        changes = []
        for k, v in filtered.items():
            old = current.get(k)
            if old != v:
                changes.append(f"{k}: {old} → {v}")

        # ★ 写回 SQLite —— 这是配置的唯一真源
        _db_update_params(bot_id, merged)

        if changes:
            rt.log("info", "参数热编辑已写入数据库：" + "；".join(changes))
            # 唤醒当前 sleep，策略下一轮从 DB 读到新值
            rt.params_changed.set()

        return _config_to_dict(_db_get(bot_id), rt)

    # -------- Stop ----------
    def stop(self, bot_id: int) -> dict:
        cfg = _db_get(bot_id)
        if cfg is None:
            raise ValueError("机器人不存在")
        rt = self._runtimes.get(bot_id)
        if not rt or not rt.running:
            _db_update_status(bot_id, "stopped", mark_stopped=True)
            return _config_to_dict(_db_get(bot_id), rt)

        rt.running = False
        rt.log("info", "收到停止指令")
        _db_update_status(bot_id, "stopped", mark_stopped=True)
        rt.params_changed.set()
        if rt.task and not rt.task.done():
            rt.task.cancel()
        return _config_to_dict(_db_get(bot_id), rt)

    def stop_all(self) -> None:
        for cid in list(self._runtimes.keys()):
            try:
                self.stop(cid)
            except Exception:
                pass

    # =========================================================================
    # 参数校验
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
            raise ValueError("单次投入金额 (USDT) 必须 > 0")
        if interval < 5:
            raise ValueError("定投间隔不能小于 5 秒")
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
    # 运行时：dispatcher（按配置行 ID 派发到具体策略）
    # =========================================================================
    async def _run(self, config_id: int) -> None:
        cfg = _db_get(config_id)
        if cfg is None:
            return
        rt = self._runtimes.get(config_id)
        if rt is None:
            return
        strategy = cfg.strategy
        try:
            if strategy == "dca":
                await self._run_dca(rt, cfg.symbol)
            elif strategy == "grid":
                await self._run_grid(rt, cfg.symbol)
            elif strategy == "ma":
                await self._run_ma(rt, cfg.symbol)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            rt.log("error", f"机器人异常退出: {type(e).__name__}: {e}")
            _db_update_status(config_id, "error", last_error=str(e))
        finally:
            rt.running = False
            # 若不是因为错误退出，标为 stopped
            cur = _db_get(config_id)
            if cur and cur.status != "error":
                _db_update_status(config_id, "stopped", mark_stopped=True)
            rt.log("info", "机器人已停止运行")

    # -------- helpers ----------
    async def _interruptible_sleep(self, rt: BotRuntime, seconds: float) -> None:
        """
        可被参数变更 / stop 打断的 sleep。
        参数一变 → DB 写入完成后 rt.params_changed.set() → sleep 立即返回
        → 下一轮 while 开头重新 SELECT params，用新参数跑。
        """
        if seconds <= 0:
            return
        rt.params_changed.clear()
        try:
            await asyncio.wait_for(rt.params_changed.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        finally:
            rt.params_changed.clear()

    async def _startup_probe(self, rt: BotRuntime, symbol: str) -> Optional[float]:
        try:
            t = await exchange.get_ticker(symbol)
            price = t["last"]
            rt.stats["last_price"] = price
            rt.consecutive_errors = 0
            _db_update_status(rt.config_id, "running")
            rt.log("info", f"探活成功，当前 {symbol} = {price:.4f}")
            return price
        except Exception as e:
            rt.log("error", f"启动探活失败: {type(e).__name__}: {e}")
            _db_update_status(
                rt.config_id, "error",
                last_error=f"启动探活失败: {e}",
                mark_stopped=True,
            )
            rt.running = False
            return None

    def _record_error(self, rt: BotRuntime, err: str) -> bool:
        """记录错误；返回是否触发熔断停机。"""
        rt.consecutive_errors += 1
        rt.log("error", err)
        _db_update_status(rt.config_id, "error", last_error=err)
        return rt.consecutive_errors >= MAX_CONSECUTIVE_ERRORS

    def _record_success(self, rt: BotRuntime) -> None:
        if rt.consecutive_errors:
            rt.consecutive_errors = 0
            _db_update_status(rt.config_id, "running", last_error=None)
        else:
            # 不写库避免噪音；状态原本就是 running
            pass

    @staticmethod
    def _qty_from_usdt(amount_usdt: float, price: float) -> float:
        """USDT 金额换算为币种数量（保留 8 位精度，支持 1 USDT 起步）。"""
        return round(amount_usdt / price, 8) if price > 0 else 0.0

    # =========================================================================
    # 策略 1：DCA
    # =========================================================================
    async def _run_dca(self, rt: BotRuntime, symbol: str) -> None:
        if await self._startup_probe(rt, symbol) is None:
            return

        while rt.running:
            # ★ 每轮从 SQLite 读最新参数 —— 用户要求的"热编辑"核心
            params = _db_read_params(rt.config_id)
            if params is None:
                rt.log("error", "数据库中配置已丢失，停机")
                return
            amount_usdt = float(params.get("amount_usdt", 0))
            interval_sec = int(params.get("interval_sec", 60))

            try:
                ticker = await exchange.get_ticker(symbol)
                last = ticker["last"]
                rt.stats["last_price"] = last

                qty = self._qty_from_usdt(amount_usdt, last)
                if qty <= 0:
                    self._record_error(rt, f"换算数量过小: {qty}（金额 {amount_usdt} / 价格 {last}）")
                else:
                    await matching.place_order(
                        symbol=symbol, side="buy", type_="market",
                        quantity=qty, price=None,
                    )
                    rt.stats["trades"] += 1
                    rt.stats["buys"] += 1
                    rt.stats["total_buy_qty"] += qty
                    rt.stats["total_spent"] += qty * last
                    rt.log(
                        "trade",
                        f"定投买入 {qty} {symbol} @ {last:.4f} "
                        f"(花费 ${qty*last:.2f} / 目标 ${amount_usdt:.2f})",
                    )
                    self._record_success(rt)
            except matching.MatchingError as e:
                stopped = self._record_error(rt, f"下单失败：{e}")
                if stopped:
                    rt.log("error", "连续错误过多，自动停机。请检查账户资金")
                    rt.running = False
                    return
            except exchange.ExchangeError as e:
                self._record_error(rt, f"行情获取失败：{e}")
            except Exception as e:
                self._record_error(rt, f"未知错误：{type(e).__name__}: {e}")

            if not rt.running:
                return
            await self._interruptible_sleep(rt, interval_sec)

    # =========================================================================
    # 策略 2：Grid
    # =========================================================================
    async def _run_grid(self, rt: BotRuntime, symbol: str) -> None:
        ref = await self._startup_probe(rt, symbol)
        if ref is None:
            return
        rt.stats["reference_price"] = ref
        rt.log("info", f"网格初始参考价 = {ref:.4f}，等待价格波动触发…")

        while rt.running:
            params = _db_read_params(rt.config_id)
            if params is None:
                rt.log("error", "数据库中配置已丢失，停机")
                return
            amount_usdt = float(params["amount_usdt"])
            drop_pct = float(params["drop_pct"]) / 100.0
            rise_pct = float(params["rise_pct"]) / 100.0
            poll_sec = int(params["poll_sec"])

            try:
                ticker = await exchange.get_ticker(symbol)
                last = ticker["last"]
                rt.stats["last_price"] = last

                buy_trigger = ref * (1 - drop_pct)
                sell_trigger = ref * (1 + rise_pct)

                if last <= buy_trigger:
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
                        await matching.place_order(
                            symbol=symbol, side="buy", type_="market",
                            quantity=qty, price=None,
                        )
                        rt.stats["trades"] += 1
                        rt.stats["buys"] += 1
                        rt.stats["total_buy_qty"] += qty
                        rt.stats["total_spent"] += qty * last
                        rt.log(
                            "trade",
                            f"⬇ 触发买入：{qty} {symbol} @ {last:.4f} "
                            f"(参考 {ref:.4f}, 跌幅 {(ref-last)/ref*100:.2f}%, 花费 ${qty*last:.2f})",
                        )
                        ref = last
                        rt.stats["reference_price"] = ref
                        self._record_success(rt)
                    except matching.MatchingError as e:
                        self._record_error(rt, f"买入失败：{e}（参考价重置）")
                        ref = last
                        rt.stats["reference_price"] = ref
                elif last >= sell_trigger:
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
                        await matching.place_order(
                            symbol=symbol, side="sell", type_="market",
                            quantity=qty, price=None,
                        )
                        rt.stats["trades"] += 1
                        rt.stats["sells"] += 1
                        rt.stats["total_sell_qty"] += qty
                        rt.stats["total_received"] += qty * last
                        rt.log(
                            "trade",
                            f"⬆ 触发卖出：{qty} {symbol} @ {last:.4f} "
                            f"(参考 {ref:.4f}, 涨幅 {(last-ref)/ref*100:.2f}%, 得 ${qty*last:.2f})",
                        )
                        ref = last
                        rt.stats["reference_price"] = ref
                        self._record_success(rt)
                    except matching.MatchingError as e:
                        self._record_error(
                            rt, f"卖出失败：{e}（可能持仓不足，参考价已重置）"
                        )
                        ref = last
                        rt.stats["reference_price"] = ref
                else:
                    self._record_success(rt)
            except exchange.ExchangeError as e:
                stopped = self._record_error(rt, f"行情失败：{e}")
                if stopped:
                    rt.running = False
                    return
            except Exception as e:
                self._record_error(rt, f"未知错误：{type(e).__name__}: {e}")

            if not rt.running:
                return
            await self._interruptible_sleep(rt, poll_sec)

    # =========================================================================
    # 策略 3：MA（双均线）
    # =========================================================================
    async def _run_ma(self, rt: BotRuntime, symbol: str) -> None:
        if await self._startup_probe(rt, symbol) is None:
            return

        prev_diff_sign: Optional[int] = None
        rt.log("info", "双均线策略已启动，等待金叉/死叉信号…")

        while rt.running:
            params = _db_read_params(rt.config_id)
            if params is None:
                rt.log("error", "数据库中配置已丢失，停机")
                return
            amount_usdt = float(params["amount_usdt"])
            ma_short = int(params["ma_short"])
            ma_long = int(params["ma_long"])
            kline_interval = str(params["kline_interval"])
            poll_sec = int(params["poll_sec"])

            try:
                need = max(ma_long + 5, ma_short + 5)
                candles = await exchange.get_kline(symbol, kline_interval, min(need, 300))
                if len(candles) < ma_long:
                    self._record_error(
                        rt, f"K 线数据不足：{len(candles)} < {ma_long}"
                    )
                    await self._interruptible_sleep(rt, poll_sec)
                    continue

                closes = [c[4] for c in candles]
                last = closes[-1]
                rt.stats["last_price"] = last

                s_val = sum(closes[-ma_short:]) / ma_short
                l_val = sum(closes[-ma_long:]) / ma_long
                rt.stats["ma_short"] = s_val
                rt.stats["ma_long"] = l_val

                diff = s_val - l_val
                cur_sign = 1 if diff > 0 else (-1 if diff < 0 else 0)

                signal = None
                if prev_diff_sign is not None and cur_sign != 0 and prev_diff_sign != cur_sign:
                    signal = "golden" if cur_sign > 0 else "death"

                if signal == "golden":
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
                        await matching.place_order(
                            symbol=symbol, side="buy", type_="market",
                            quantity=qty, price=None,
                        )
                        rt.stats["trades"] += 1
                        rt.stats["buys"] += 1
                        rt.stats["total_buy_qty"] += qty
                        rt.stats["total_spent"] += qty * last
                        rt.log(
                            "trade",
                            f"🌟 金叉买入 {qty} {symbol} @ {last:.4f} "
                            f"(MA{ma_short}={s_val:.4f} 上穿 MA{ma_long}={l_val:.4f})"
                        )
                        self._record_success(rt)
                    except matching.MatchingError as e:
                        self._record_error(rt, f"金叉买入失败：{e}")
                elif signal == "death":
                    qty = self._qty_from_usdt(amount_usdt, last)
                    try:
                        await matching.place_order(
                            symbol=symbol, side="sell", type_="market",
                            quantity=qty, price=None,
                        )
                        rt.stats["trades"] += 1
                        rt.stats["sells"] += 1
                        rt.stats["total_sell_qty"] += qty
                        rt.stats["total_received"] += qty * last
                        rt.log(
                            "trade",
                            f"💀 死叉卖出 {qty} {symbol} @ {last:.4f} "
                            f"(MA{ma_short}={s_val:.4f} 下穿 MA{ma_long}={l_val:.4f})"
                        )
                        self._record_success(rt)
                    except matching.MatchingError as e:
                        self._record_error(rt, f"死叉卖出失败（可能持仓不足）：{e}")
                else:
                    self._record_success(rt)

                prev_diff_sign = cur_sign
            except exchange.ExchangeError as e:
                stopped = self._record_error(rt, f"行情失败：{e}")
                if stopped:
                    rt.running = False
                    return
            except Exception as e:
                self._record_error(rt, f"未知错误：{type(e).__name__}: {e}")

            if not rt.running:
                return
            await self._interruptible_sleep(rt, poll_sec)


bot_manager = BotManager()
