"""
SQLite + SQLModel 持久化层。
表：
- account    : 单行虚拟账户（现金余额）
- position   : 持仓（按 symbol 汇总，含均价）
- order      : 挂单 / 成交 / 撤单
- trade      : 成交流水
- bot_config : 自动交易机器人配置（参数落盘，支持热编辑 + 重启后可查）

★ 所有 datetime 列默认使用北京时间（UTC+8）。
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, Session, create_engine, select

from app.config import settings
from app.core.time import now_cn


# ---------- Models ----------
class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    cash: float
    initial_capital: float
    created_at: datetime = Field(default_factory=now_cn)


class Position(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, unique=True)
    quantity: float = 0.0
    avg_price: float = 0.0
    updated_at: datetime = Field(default_factory=now_cn)


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)
    side: str                       # "buy" | "sell"
    type: str                       # "market" | "limit"
    quantity: float
    price: Optional[float] = None   # 限价单价格；市价单忽略
    status: str = Field(default="open", index=True)  # open|filled|cancelled
    filled_price: Optional[float] = None
    filled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now_cn)


class Trade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(index=True)
    symbol: str = Field(index=True)
    side: str
    quantity: float
    price: float
    # 成交手续费（USDT），已从账户现金中扣除/少收。可能为 0（老数据 / 手续费率为 0）
    fee: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=now_cn)


class EquitySnapshot(SQLModel, table=True):
    """
    账户净值快照 —— 每分钟由后台任务写入一次。
    用于前端绘制"资产随时间变化"折线图（类比 Apple Stocks）。
    注：保留所有点，不做清理；按一年 525600 条 × 约 80 B/行 ≈ 42 MB，可接受。
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=now_cn, index=True)
    total_equity: float
    cash: float
    position_value: float
    unrealized_pnl: float


class BotConfig(SQLModel, table=True):
    """
    自动交易机器人配置（策略参数持久化）。
    - params_json: 策略参数字典的 JSON 字符串（SQLite 没有原生 JSON 列，存字符串即可）
    - status:      initializing | running | error | stopped
    - 策略循环每轮都会 SELECT 当前行拿最新的 params_json，实现"热编辑"
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str = Field(index=True)           # dca | grid | ma
    symbol: str = Field(index=True)
    params_json: str                            # JSON 字符串
    status: str = Field(default="initializing", index=True)
    last_error: Optional[str] = None
    started_at: datetime = Field(default_factory=now_cn)
    stopped_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=now_cn)


# ---------- Engine ----------
_engine = create_engine(
    f"sqlite:///{settings.DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


def get_engine():
    return _engine


def get_session() -> Session:
    return Session(_engine)


def init_db() -> None:
    """首次启动建表 + 初始化账户 + 轻量迁移。"""
    SQLModel.metadata.create_all(_engine)
    # 轻量迁移：给老数据库补上新字段（SQLite ALTER TABLE 支持 ADD COLUMN）
    _migrate_add_column_if_missing("trade", "fee", "REAL DEFAULT 0.0")
    with Session(_engine) as session:
        acc = session.exec(select(Account).where(Account.id == 1)).first()
        if acc is None:
            acc = Account(
                id=1,
                cash=settings.INITIAL_CAPITAL,
                initial_capital=settings.INITIAL_CAPITAL,
            )
            session.add(acc)
            session.commit()


def _migrate_add_column_if_missing(table: str, column: str, sql_type: str) -> None:
    """幂等地给已存在的表补字段；不存在就加，存在就跳过。"""
    from sqlalchemy import text
    with _engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        existing = {r[1] for r in rows}  # row[1] = column name
        if column in existing:
            return
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
