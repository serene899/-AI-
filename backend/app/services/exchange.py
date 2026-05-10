"""
OKX 公共行情封装。
- OKX V5 公共接口无需 API Key
- 文档: https://www.okx.com/docs-v5/
统一 symbol 格式: BTC-USDT (OKX 原生风格)

v2 变更：
    - httpx timeout 10s -> 5s，避免单次慢请求拖死整个前端 poll
    - 加 TTL 缓存（ticker 2s / kline 5s），同一 symbol 短时多次调用直接命中缓存
    - 失败回退到上次缓存（如有），避免 portfolio 雪崩
"""
import asyncio
import time
from typing import Any, Optional
import httpx

from app.config import settings


OKX_BASE = "https://www.okx.com"
HTTP_TIMEOUT = 5.0   # 不超过前端 15s 轮询预算的 1/3
TICKER_TTL = 2.0     # 秒
KLINE_TTL = 5.0

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


# ---- 简易内存缓存 ----
_ticker_cache: dict[str, tuple[float, dict]] = {}          # symbol -> (ts, data)
_tickers_cache: dict[tuple, tuple[float, list]] = {}       # key(tuple) -> (ts, data)
_kline_cache: dict[tuple, tuple[float, list]] = {}         # (symbol, interval, limit) -> (ts, data)


def _cache_get(store: dict, key, ttl: float):
    item = store.get(key)
    if item is None:
        return None
    ts, data = item
    if time.time() - ts <= ttl:
        return data
    return None


def _cache_set(store: dict, key, data):
    store[key] = (time.time(), data)


async def _get(path: str, params: dict | None = None) -> Any:
    url = f"{OKX_BASE}{path}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
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
    """获取单个交易对的最新 ticker。TTL 缓存 2s；失败回退最近缓存。"""
    cached = _cache_get(_ticker_cache, symbol, TICKER_TTL)
    if cached is not None:
        return cached
    try:
        data = await _get("/api/v5/market/ticker", {"instId": symbol})
        if not data:
            raise ExchangeError(f"No ticker for {symbol}")
        t = data[0]
        result = {
            "symbol": t["instId"],
            "last": float(t["last"]),
            "bid": float(t.get("bidPx") or 0),
            "ask": float(t.get("askPx") or 0),
            "high24h": float(t.get("high24h") or 0),
            "low24h": float(t.get("low24h") or 0),
            "vol24h": float(t.get("vol24h") or 0),
            "ts": int(t.get("ts") or 0),
        }
        _cache_set(_ticker_cache, symbol, result)
        return result
    except Exception:
        # 回退：如果缓存里有旧数据，即便过期也先用着，避免前端卡死
        stale = _ticker_cache.get(symbol)
        if stale is not None:
            return stale[1]
        raise


async def get_tickers(symbols: list[str] | None = None) -> list[dict]:
    """批量获取 ticker；OKX 一次性拉 SPOT 全量再筛。带 2s 缓存。"""
    symbols = symbols or DEFAULT_SYMBOLS
    key = tuple(symbols)
    cached = _cache_get(_tickers_cache, key, TICKER_TTL)
    if cached is not None:
        return cached
    try:
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
        _cache_set(_tickers_cache, key, result)
        return result
    except Exception:
        stale = _tickers_cache.get(key)
        if stale is not None:
            return stale[1]
        raise


async def get_kline(symbol: str, interval: str = "1m", limit: int = 100) -> list[list]:
    """
    OKX K 线。TTL 缓存 5s。
    interval: 1m 3m 5m 15m 30m 1H 2H 4H 6H 12H 1D 1W 1M
    返回: [[ts, open, high, low, close, vol], ...] 时间升序
    """
    key = (symbol, interval, limit)
    cached = _cache_get(_kline_cache, key, KLINE_TTL)
    if cached is not None:
        return cached
    # OKX 的 bar 参数大小写：分钟小写 m，小时大写 H，日 D
    bar_map = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
        "1d": "1D", "1w": "1W", "1M": "1M",
    }
    bar = bar_map.get(interval.lower(), "1m")
    try:
        raw = await _get(
            "/api/v5/market/candles",
            {"instId": symbol, "bar": bar, "limit": str(limit)},
        )
    except Exception:
        stale = _kline_cache.get(key)
        if stale is not None:
            return stale[1]
        raise
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
    _cache_set(_kline_cache, key, candles)
    return candles
