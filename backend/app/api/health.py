"""健康检查。"""
import time
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.response import ok

router = APIRouter()

_START_TS = time.time()
VERSION = "1.0.0"


@router.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "uptime_seconds": int(time.time() - _START_TS),
    }


@router.get("/api/v1/config", tags=["system"])
async def config():
    from app.services.exchange import DEFAULT_SYMBOLS
    from app.config import settings
    return ok({
        "exchange": settings.EXCHANGE,
        "symbols": DEFAULT_SYMBOLS,
        "version": VERSION,
    })
