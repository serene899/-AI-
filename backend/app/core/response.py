"""统一 API 响应格式。"""
from typing import Any, Optional
from pydantic import BaseModel


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Optional[Any] = None


def ok(data: Any = None, message: str = "ok") -> dict:
    return ApiResponse(code=0, message=message, data=data).model_dump()


def fail(message: str, code: int = 1, data: Any = None) -> dict:
    return ApiResponse(code=code, message=message, data=data).model_dump()
