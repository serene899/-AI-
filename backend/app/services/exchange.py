"""
OKX 公共行情封装。
- OKX V5 公共接口无需 API Key
- 文档: https://www.okx.com/docs-v5/
统一 symbol 格式: BTC-USDT (OKX 原生风格)
"""
from typing import Any
import httpx

from app.config import settings


OKX_BASE = "https://www.okx.com"

# 默认热门交易对
DEFAULT_SYMBOLS = [
    "BTC-USDT",
    "ETH-USDT",
    "SOL-USDT",
    "BNB-USDT",
    "XRP-USDT",
    "DOGE-USDT",
]


class ExchangeError(Exception):
    pass


async def _get(path: str, params: dict | None = None) -> Any:
    url = f"{OKX_BASE}{path}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise ExchangeError(f"OKX request failed: {e}") from e

    if data.get("code") != "0":
        raise ExchangeError(f"OKX API error: {data.get('msg')}")
    return data.get("data", [])


async def get_ticker(symbol: str) -> dict:
    """获取单个交易对的最新 ticker。"""
    data = await _get("/api/v5/market/ticker", {"instId": symbol})
    if not data:
        raise ExchangeError(f"No ticker for {symbol}")
    t = data[0]
    return {
        "symbol": t["instId"],
        "last": float(t["last"]),
        "bid": float(t.get("bidPx") or 0),
        "ask": float(t.get("askPx") or 0),
        "high24h": float(t.get("high24h") or 0),
        "low24h": float(t.get("low24h") or 0),
        "vol24h": float(t.get("vol24h") or 0),
        "ts": int(t.get("ts") or 0),
    }


async def get_tickers(symbols: list[str] | None = None) -> list[dict]:
    """批量获取 ticker；OKX 一次性拉 SPOT 全量再筛。"""
    symbols = symbols or DEFAULT_SYMBOLS
    data = await _get("/api/v5/market/tickers", {"instType": "SPOT"})
    wanted = set(symbols)
    result = []
    for t in data:
        if t["instId"] in wanted:
            result.append({
                "symbol": t["instId"],
                "last": float(t["last"]),
                "high24h": float(t.get("high24h") or 0),
                "low24h": float(t.get("low24h") or 0),
                "vol24h": float(t.get("vol24h") or 0),
                "change24h": (
                    (float(t["last"]) - float(t.get("open24h") or t["last"]))
                    / float(t.get("open24h") or 1)
                ) if t.get("open24h") else 0.0,
            })
    # 保持用户请求顺序
    order = {s: i for i, s in enumerate(symbols)}
    result.sort(key=lambda x: order.get(x["symbol"], 999))
    return result


async def get_kline(symbol: str, interval: str = "1m", limit: int = 100) -> list[list]:
    """
    OKX K 线。
    interval: 1m 3m 5m 15m 30m 1H 2H 4H 6H 12H 1D 1W 1M
    返回: [[ts, open, high, low, close, vol], ...] 时间升序
    """
    # OKX 的 bar 参数大小写：分钟小写 m，小时大写 H，日 D
    bar_map = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
        "1d": "1D", "1w": "1W", "1M": "1M",
    }
    bar = bar_map.get(interval.lower(), "1m")
    raw = await _get(
        "/api/v5/market/candles",
        {"instId": symbol, "bar": bar, "limit": str(limit)},
    )
    # OKX 返回时间降序，前端需要升序
    candles = []
    for row in reversed(raw):
        candles.append([
            int(row[0]),        # ts (ms)
            float(row[1]),      # open
            float(row[2]),      # high
            float(row[3]),      # low
            float(row[4]),      # close
            float(row[5]),      # vol
        ])
    return candles
