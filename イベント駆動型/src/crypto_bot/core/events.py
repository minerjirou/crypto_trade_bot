from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class RecordedEvent:
    event_type: str
    payload: dict[str, Any]
    recorded_at: datetime


@dataclass(slots=True)
class RunRecord:
    run_id: str
    mode: str
    started_at: datetime
    config_path: str
    config_snapshot: dict[str, Any]


@dataclass(slots=True)
class AgentNote:
    run_id: str
    note_type: str
    summary: str
    created_at: datetime
    symbol: str | None = None
    details: dict[str, Any] | None = None
