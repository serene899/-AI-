"""
SQLite + SQLModel 持久化层。
表：
- account    : 单行虚拟账户（现金余额）
- position   : 持仓（按 symbol 汇总，含均价）
- order      : 挂单 / 成交 / 撤单
- trade      : 成交流水
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel, Session, create_engine, select

from app.config import settings


# ---------- Models ----------
class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    cash: float
    initial_capital: float
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Position(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, unique=True)
    quantity: float = 0.0
    avg_price: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Trade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(index=True)
    symbol: str = Field(index=True)
    side: str
    quantity: float
    price: float
    created_at: datetime = Field(default_factory=datetime.utcnow)


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
    """首次启动建表 + 初始化账户。"""
    SQLModel.metadata.create_all(_engine)
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
