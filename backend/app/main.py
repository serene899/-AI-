"""
FastAPI 入口。
- CORS
- 路由注册
- 启动时建表 + 拉起限价单撮合 + 从数据库恢复机器人
- 关闭时只 cancel 任务；DB 状态保留，下次启动继续
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

    # ★ 关键：从 SQLite 恢复运行中的机器人（重启 / 刷新都不丢）
    from app.services.bot import bot_manager
    try:
        restored = await bot_manager.resume_from_db()
        if restored:
            log.info("✓ 从数据库恢复了 %d 个机器人", restored)
        else:
            log.info("数据库中没有需要恢复的运行中机器人")
    except Exception as e:
        log.error("恢复机器人失败: %s", e)

    log.info("Backend ready. CORS origins: %s", settings.cors_origins_list)


@app.on_event("shutdown")
async def on_shutdown():
    """
    优雅关机：只取消异步 task，不改 DB 里的 status。
    这样下次启动时还能把这些机器人恢复回来。
    """
    from app.services.bot import bot_manager
    log.info("Shutdown: 取消运行中的机器人任务，DB 状态保留以便下次恢复...")
    bot_manager.cancel_tasks_preserve_status()


@app.get("/")
async def root():
    return {
        "name": "Crypto Sim Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }

