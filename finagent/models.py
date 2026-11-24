from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Metric:
    name: str
    value: Any
    unit: str = ""
    source: str = ""
    retrieved_at: str = field(default_factory=now_iso)


@dataclass
class FinancialSnapshot:
    ticker: str
    company: str
    provider: str
    metrics: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    demo: bool = False


@dataclass
class SourceDoc:
    title: str
    url: str
    snippet: str
    retrieved_at: str = field(default_factory=now_iso)
    flagged: bool = False  # True if prompt-injection patterns were detected


@dataclass
class Response:
    status: str  # OK | DEGRADED | UNAVAILABLE | NEEDS_INPUT | REFUSED | STOPPED
    ticker: Optional[str]
    markdown: str
    snapshot: Optional[FinancialSnapshot] = None
    sources: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    latency_ms: int = 0
    trace: dict = field(default_factory=dict)
