"""自动交易机器人 API。"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.services.bot import bot_manager

router = APIRouter(prefix="/api/v1/bot", tags=["bot"])


class StartBotReq(BaseModel):
    strategy: str = Field(..., description="dca | grid")
    symbol: str = Field(..., description="如 BTC-USDT")
    params: dict = Field(..., description="策略参数")


@router.get("/strategies")
async def list_strategies():
    """返回可用策略及参数说明（供前端生成表单）。"""
    return ok([
        {
            "key": "dca",
            "name": "定投 DCA",
            "description": "每隔固定时间买入固定金额，适合新手长期持有",
            "fields": [
                {"name": "amount_usdt", "label": "每次买入金额 (USDT)", "type": "number", "default": 100, "min": 1},
                {"name": "interval_sec", "label": "间隔时间 (秒)", "type": "number", "default": 60, "min": 5},
            ],
        },
        {
            "key": "grid",
            "name": "智能网格",
            "description": "跌 X% 买入、涨 Y% 卖出，适合震荡行情",
            "fields": [
                {"name": "quantity", "label": "每次交易数量", "type": "number", "default": 0.001, "min": 0},
                {"name": "drop_pct", "label": "跌幅触发买入 (%)", "type": "number", "default": 1.0, "min": 0.1, "max": 50},
                {"name": "rise_pct", "label": "涨幅触发卖出 (%)", "type": "number", "default": 1.0, "min": 0.1, "max": 50},
                {"name": "poll_sec", "label": "轮询间隔 (秒)", "type": "number", "default": 3, "min": 1},
            ],
        },
    ])


@router.get("")
async def list_bots(status: Optional[str] = Query(None, description="running | stopped")):
    return ok(bot_manager.list(status=status))


@router.post("/start")
async def start_bot(body: StartBotReq):
    try:
        data = await bot_manager.start(body.strategy, body.symbol, body.params)
        return ok(data, message="机器人已启动")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stop/{bot_id}")
async def stop_bot(bot_id: int):
    try:
        data = bot_manager.stop(bot_id)
        return ok(data, message="机器人已停止")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{bot_id}")
async def get_bot(bot_id: int):
    data = bot_manager.get(bot_id)
    if data is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return ok(data)
