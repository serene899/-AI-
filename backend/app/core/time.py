"""
统一时区工具 —— 存储用 UTC，展示用 Asia/Shanghai。

存储约定（和业内通用做法一致）：
    - 数据库里所有 datetime 列存 naive UTC（即 datetime.utcnow() 的输出）。
      这样旧数据（此前就是 utcnow 写进去的）零成本兼容。
    - 展示/序列化时一律通过 iso_cn()，把 naive UTC 按 UTC 解释后转到 CN
      时区，输出带 '+08:00' 后缀，前端 new Date 能正确解析。

    永远不要让展示逻辑和存储逻辑共享"这个 datetime 是什么时区"的假设，
    由这个模块统一把关，业务代码只需：
        now_utc()         # 写库
        iso_cn(dt)        # 读库->前端
        ts_to_cn_iso(ts)  # 运行时 epoch -> 前端
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_utc() -> datetime:
    """UTC naive，存库用；与旧代码的 datetime.utcnow() 语义一致。"""
    return datetime.utcnow()


# 保留旧名字作为别名，方便外部调用方不改名
now_cn = now_utc


def _to_cn_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """把任意 datetime 规范化为带 +08:00 tzinfo 的 aware datetime。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # 存储约定：naive 就是 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN_TZ)


def iso_cn(dt: Optional[datetime]) -> Optional[str]:
    """序列化为带 +08:00 后缀的 ISO 字符串。"""
    v = _to_cn_aware(dt)
    return v.isoformat() if v else None


def ts_to_cn_iso(ts: float) -> str:
    """epoch 秒 -> 北京时间 ISO 字符串（运行时日志用）。"""
    return datetime.fromtimestamp(ts, CN_TZ).isoformat()
