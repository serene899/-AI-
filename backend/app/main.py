"""
FastAPI 入口。
- CORS
- 路由注册
- 启动时建表 + 拉起限价单撮合后台任务
"""
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import account, bot, health, market, trade
from app.config import settings
from app.models.db import init_db
from app.services.matching import limit_order_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("cryptosim")

app = FastAPI(
    title="Crypto Sim Backend",
    description="加密货币自动交易模拟系统 — 后端 API",
    version="1.0.0",
)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Routes ----------
app.include_router(health.router)
app.include_router(market.router)
app.include_router(account.router)
app.include_router(trade.router)
app.include_router(bot.router)


# ---------- Lifecycle ----------
@app.on_event("startup")
async def on_startup():
    log.info("Initializing database at %s ...", settings.DB_PATH)
    init_db()
    log.info("Starting limit-order matching worker ...")
    asyncio.create_task(limit_order_worker(interval_sec=2.0))
    log.info("Backend ready. CORS origins: %s", settings.cors_origins_list)


@app.on_event("shutdown")
async def on_shutdown():
    from app.services.bot import bot_manager
    log.info("Stopping all running bots ...")
    bot_manager.stop_all()


@app.get("/")
async def root():
    return {
        "name": "Crypto Sim Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
