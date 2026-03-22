from __future__ import annotations

from decimal import Decimal
from typing import Any

from crypto_bot.storage.sqlite import SqliteRecorder


class ReportBuilder:
    def __init__(self, recorder: SqliteRecorder) -> None:
        self._recorder = recorder

    def build_run_report(self, run_id: str) -> dict[str, Any]:
        bundle = self._recorder.build_analysis_bundle(run_id)
        outcomes = bundle["outcomes"]
        net_pnl = sum((Decimal(str(row["net_pnl"])) for row in outcomes), start=Decimal("0"))
        reject_counts: dict[str, int] = {}
        for row in bundle["journal"]:
            reason = row.get("decision_reason")
            if reason is None:
                continue
            reject_counts[reason] = reject_counts.get(reason, 0) + 1
        return {
            "run": bundle["run"],
            "signal_count": len(bundle["journal"]),
            "order_count": len(bundle["orders"]),
            "fill_count": len(bundle["fills"]),
            "trade_count": len(outcomes),
            "net_pnl": str(net_pnl),
            "reject_counts": reject_counts,
        }
