"""自动交易机器人 API。"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.services.bot import STRATEGY_DEFS, bot_manager

router = APIRouter(prefix="/api/v1/bot", tags=["bot"])


class StartBotReq(BaseModel):
    strategy: str = Field(..., description="dca | grid | ma")
    symbol: str = Field(..., description="如 BTC-USDT")
    params: dict = Field(..., description="策略参数")


class UpdateParamsReq(BaseModel):
    params: dict = Field(..., description="要更新的参数（只更新 hot 字段）")


@router.get("/strategies")
async def list_strategies():
    """返回可用策略及参数说明（前端用来动态生成表单）。"""
    return ok(STRATEGY_DEFS)


@router.get("")
async def list_bots():
    return ok(bot_manager.list())


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


@router.post("/stop-all")
async def stop_all():
    """一键停止所有机器人。"""
    bot_manager.stop_all()
    return ok(bot_manager.list(), message="所有机器人已停止")


@router.patch("/{bot_id}/params")
async def update_params(bot_id: int, body: UpdateParamsReq):
    """热更新参数（仅限 strategy 标记为 hot=True 的字段）。"""
    try:
        data = bot_manager.update_params(bot_id, body.params)
        return ok(data, message="参数已热更新，下一轮立即生效")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{bot_id}")
async def get_bot(bot_id: int):
    data = bot_manager.get(bot_id)
    if data is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return ok(data)


@router.get("/{bot_id}/logs")
async def get_bot_logs(
    bot_id: int,
    since_ts: float = Query(0.0, description="只返回此 epoch 秒之后的日志，实现增量拉取"),
):
    """增量拉日志，减少带宽。"""
    # 先校验机器人是否存在（走公共 API，不依赖内部字段名）
    if bot_manager.get(bot_id) is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    return ok(bot_manager.get_logs(bot_id, since_ts=since_ts))
