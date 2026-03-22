from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from crypto_bot.core.events import AgentNote, RecordedEvent, RunRecord
from crypto_bot.core.models import ExecutionPlan, FeatureSnapshot, RiskDecision, SignalCandidate


class SqliteRecorder:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()
        self._conn.commit()

    def _create_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT,
                config_path TEXT NOT NULL,
                config_snapshot TEXT NOT NULL,
                metrics_json TEXT
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_side TEXT,
                basis TEXT NOT NULL,
                basis_z TEXT NOT NULL,
                funding_rate TEXT NOT NULL,
                spread_bps TEXT NOT NULL,
                volume_acceleration TEXT NOT NULL,
                oi_acceleration TEXT NOT NULL,
                listing_age_days INTEGER NOT NULL,
                depth_usd_at_5bps TEXT NOT NULL,
                candidate_generated INTEGER NOT NULL,
                approved INTEGER,
                decision_reason TEXT,
                score TEXT,
                entry_price TEXT,
                stop_price TEXT,
                target_price TEXT,
                size_quote TEXT,
                leverage TEXT,
                planned_order_count INTEGER,
                account_equity TEXT NOT NULL,
                open_positions_count INTEGER NOT NULL,
                feature_json TEXT NOT NULL,
                candidate_json TEXT,
                decision_json TEXT,
                execution_plan_json TEXT
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signal_journal_run_time ON signal_journal(run_id, observed_at)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signal_journal_symbol ON signal_journal(symbol, observed_at)"
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                note_type TEXT NOT NULL,
                symbol TEXT,
                summary TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_notes_run_time ON agent_notes(run_id, created_at)"
        )

    def record(self, event: RecordedEvent) -> None:
        self._conn.execute(
            "INSERT INTO events(event_type, payload, recorded_at) VALUES (?, ?, ?)",
            (
                event.event_type,
                json.dumps(self._serialize(event.payload), ensure_ascii=True),
                event.recorded_at.isoformat(),
            ),
        )
        self._conn.commit()

    def begin_run(self, run: RunRecord) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO runs(run_id, mode, started_at, config_path, config_snapshot)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.mode,
                run.started_at.isoformat(),
                run.config_path,
                json.dumps(self._serialize(run.config_snapshot), ensure_ascii=True),
            ),
        )
        self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        ended_at: datetime,
        status: str,
        metrics: dict[str, Any],
    ) -> None:
        self._conn.execute(
            """
            UPDATE runs
            SET ended_at = ?, status = ?, metrics_json = ?
            WHERE run_id = ?
            """,
            (
                ended_at.isoformat(),
                status,
                json.dumps(self._serialize(metrics), ensure_ascii=True),
                run_id,
            ),
        )
        self._conn.commit()

    def record_signal_journal(
        self,
        *,
        run_id: str,
        feature: FeatureSnapshot,
        account_equity: Decimal,
        open_positions_count: int,
        candidate: SignalCandidate | None = None,
        decision: RiskDecision | None = None,
        plan: ExecutionPlan | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO signal_journal(
                run_id,
                observed_at,
                exchange,
                symbol,
                signal_side,
                basis,
                basis_z,
                funding_rate,
                spread_bps,
                volume_acceleration,
                oi_acceleration,
                listing_age_days,
                depth_usd_at_5bps,
                candidate_generated,
                approved,
                decision_reason,
                score,
                entry_price,
                stop_price,
                target_price,
                size_quote,
                leverage,
                planned_order_count,
                account_equity,
                open_positions_count,
                feature_json,
                candidate_json,
                decision_json,
                execution_plan_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                feature.observed_at.isoformat(),
                feature.instrument.exchange.value,
                feature.instrument.symbol,
                candidate.side.value if candidate else None,
                str(feature.basis),
                str(feature.basis_z),
                str(feature.funding_rate),
                str(feature.spread_bps),
                str(feature.volume_acceleration),
                str(feature.oi_acceleration),
                feature.listing_age_days,
                str(feature.depth_usd_at_5bps),
                1 if candidate else 0,
                None if decision is None else int(decision.approved),
                decision.reason.value if decision else None,
                str(candidate.score) if candidate else None,
                str(candidate.entry_price) if candidate else None,
                str(candidate.stop_price) if candidate else None,
                str(candidate.target_price) if candidate else None,
                str(decision.size_quote) if decision else None,
                str(decision.leverage) if decision else None,
                None if plan is None else len(plan.intents),
                str(account_equity),
                open_positions_count,
                json.dumps(self._serialize(feature), ensure_ascii=True),
                None if candidate is None else json.dumps(self._serialize(candidate), ensure_ascii=True),
                None if decision is None else json.dumps(self._serialize(decision), ensure_ascii=True),
                None if plan is None else json.dumps(self._serialize(plan), ensure_ascii=True),
            ),
        )
        self._conn.commit()

    def add_agent_note(self, note: AgentNote) -> None:
        self._conn.execute(
            """
            INSERT INTO agent_notes(run_id, note_type, symbol, summary, details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                note.run_id,
                note.note_type,
                note.symbol,
                note.summary,
                json.dumps(self._serialize(note.details or {}), ensure_ascii=True),
                note.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def build_analysis_bundle(self, run_id: str, limit: int = 200) -> dict[str, Any]:
        run_row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        journal_rows = self._conn.execute(
            """
            SELECT * FROM signal_journal
            WHERE run_id = ?
            ORDER BY observed_at ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
        note_rows = self._conn.execute(
            """
            SELECT * FROM agent_notes
            WHERE run_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()
        return {
            "run": None if run_row is None else self._decode_row(dict(run_row)),
            "journal": [self._decode_row(dict(row)) for row in journal_rows],
            "notes": [self._decode_row(dict(row)) for row in note_rows],
        }

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, timedelta):
            return value.total_seconds()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return str(value)
        if is_dataclass(value):
            return {key: SqliteRecorder._serialize(item) for key, item in asdict(value).items()}
        if isinstance(value, dict):
            return {key: SqliteRecorder._serialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [SqliteRecorder._serialize(item) for item in value]
        return value

    @staticmethod
    def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
        for key in (
            "config_snapshot",
            "metrics_json",
            "feature_json",
            "candidate_json",
            "decision_json",
            "execution_plan_json",
            "details_json",
        ):
            value = row.get(key)
            if isinstance(value, str) and value:
                row[key] = json.loads(value)
        return row
