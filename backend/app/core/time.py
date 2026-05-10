"""
统一时区工具 —— 系统默认 Asia/Shanghai (UTC+8)。

设计原则：
1) 新生成的时间戳使用 `now_cn()`，返回 aware datetime（带 +08:00 时区信息）
2) 从 DB 读出的老数据如果是 naive（没时区信息）则兜底为 UTC 再转 CN，
   这样之前库里按 utcnow() 存的值不会偏移
3) 序列化交给前端的时间一律带 '+08:00' 后缀，前端拿到后无论跑在哪个时区
   的浏览器里都能正确还原

注：使用固定偏移 UTC+8 而非 ZoneInfo("Asia/Shanghai")。
   中国大陆自 1991 年起没有夏令时，恒定 UTC+8，固定偏移足够用，
   且避免部分精简部署环境缺 tzdata 数据库的问题。
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_cn() -> datetime:
    """返回当前北京时间（aware datetime, UTC+8）。供 DB default_factory 使用。"""
    return datetime.now(CN_TZ)


def to_cn(dt: Optional[datetime]) -> Optional[datetime]:
    """
    把任意 datetime 转成北京时间 aware datetime。
    naive 的老数据假定为 UTC（兼容重构前 datetime.utcnow() 存入的值）。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN_TZ)


def iso_cn(dt: Optional[datetime]) -> Optional[str]:
    """序列化为带 +08:00 后缀的 ISO 字符串。DB/日志时间一律过这个函数。"""
    v = to_cn(dt)
    return v.isoformat() if v else None


def ts_to_cn_iso(ts: float) -> str:
    """epoch 秒 -> 北京时间 ISO 字符串。用于日志条目。"""
    return datetime.fromtimestamp(ts, CN_TZ).isoformat()
