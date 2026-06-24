"""Health check and metrics schemas."""

from datetime import datetime

from pydantic import BaseModel


class SystemMetrics(BaseModel):
    """System metrics."""

    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: float
    python_version: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str
    environment: str
    timestamp: datetime
    database: str = "connected"
    redis: str | None = None
    celery: str | None = None


class MetricsResponse(BaseModel):
    """Detailed metrics response."""

    system: SystemMetrics
    database: dict[str, int]  # table counts
    api: dict[str, int]  # request counts
    solver: dict[str, float]  # solver stats
