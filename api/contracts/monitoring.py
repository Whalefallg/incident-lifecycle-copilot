from typing import Any, Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["healthy"]
    service: str


class SystemStatsResponse(BaseModel):
    status: Literal["ok", "error"]
    cache: dict[str, Any] | None = None
    model_routing: dict[str, Any] | None = None
    estimated_total_savings_percent: float | None = None
    error: str | None = None


class RedisInfoResponse(BaseModel):
    status: Literal["ok", "error"]
    redis_version: str | None = None
    uptime_seconds: int | None = None
    db_size: int | None = None
    used_memory_human: str | None = None
    error: str | None = None
