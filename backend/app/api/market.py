"""行情接口。"""
from fastapi import APIRouter, HTTPException, Query

from app.core.response import ok
from app.services import exchange

router = APIRouter(prefix="/api/v1/market", tags=["market"])


@router.get("/ticker")
async def ticker(symbol: str = Query(..., description="如 BTC-USDT")):
    try:
        data = await exchange.get_ticker(symbol)
        return ok(data)
    except exchange.ExchangeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/tickers")
async def tickers(symbols: str | None = Query(None, description="逗号分隔；为空则返回默认热门")):
    syms = [s.strip() for s in symbols.split(",")] if symbols else None
    try:
        data = await exchange.get_tickers(syms)
        return ok(data)
    except exchange.ExchangeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/kline")
async def kline(
    symbol: str = Query(...),
    interval: str = Query("1m"),
    limit: int = Query(100, ge=1, le=300),
):
    try:
        data = await exchange.get_kline(symbol, interval, limit)
        return ok({"symbol": symbol, "interval": interval, "candles": data})
    except exchange.ExchangeError as e:
        raise HTTPException(status_code=502, detail=str(e))
