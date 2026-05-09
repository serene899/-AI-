"""Pydantic 请求/响应 Schema。"""
from typing import Optional
from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    symbol: str = Field(..., description="例如 BTC-USDT")
    side: str = Field(..., pattern="^(buy|sell)$")
    type: str = Field(..., pattern="^(market|limit)$")
    quantity: float = Field(..., gt=0)
    price: Optional[float] = Field(None, gt=0, description="限价单必填")


class AccountReset(BaseModel):
    initial_capital: float = Field(10000.0, gt=0)
