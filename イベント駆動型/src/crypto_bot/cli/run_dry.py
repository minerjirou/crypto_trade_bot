from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from crypto_bot.adapters.dry_run import DryRunExchangeAdapter
from crypto_bot.core.config import Settings
from crypto_bot.core.events import AgentNote, RecordedEvent, RunRecord
from crypto_bot.core.logging import setup_logging
from crypto_bot.core.models import ExchangeName, Instrument, MarketSnapshot, UTC
from crypto_bot.execution.order_manager import OrderManager
from crypto_bot.features.basis import FeatureEngine
from crypto_bot.risk.engine import AccountState, RiskEngine
from crypto_bot.storage.sqlite import SqliteRecorder
from crypto_bot.strategies.basis_extreme import BasisExtremeStrategy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run crypto bot in dry-run mode")
    parser.add_argument(
        "--config",
        default="config/settings.example.yaml",
        type=Path,
        help="Path to YAML settings file",
    )
    return parser


def sample_snapshots() -> list[MarketSnapshot]:
    instrument = Instrument(
        exchange=ExchangeName.DRY_RUN,
        symbol="ALTUSDT",
        base="ALT",
        quote="USDT",
        spot_symbol="ALTUSDT",
        perp_symbol="ALTUSDT_PERP",
        listing_time=datetime.now(tz=UTC) - timedelta(days=90),
        tick_size=Decimal("0.001"),
        lot_size=Decimal("0.001"),
        min_notional=Decimal("5"),
    )
    snapshots: list[MarketSnapshot] = []
    for offset, perp in enumerate(["1.000", "1.001", "1.000", "0.999", "0.995", "0.990", "0.850", "0.780"]):
        snapshots.append(
            MarketSnapshot(
                instrument=instrument,
                spot_bid=Decimal("0.9995"),
                spot_ask=Decimal("1.0005"),
                perp_bid=Decimal(perp) - Decimal("0.001"),
                perp_ask=Decimal(perp) + Decimal("0.001"),
                funding_rate=Decimal("0.0001"),
                volume_24h_usd=Decimal("1200000") + Decimal(offset * 50000),
                open_interest_usd=Decimal("900000") + Decimal(offset * 25000),
                depth_usd_at_5bps=Decimal("35000"),
                observed_at=datetime.now(tz=UTC) + timedelta(minutes=offset),
            )
        )
    return snapshots


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.load(args.config)
    setup_logging()
    logger = logging.getLogger("crypto_bot")
    recorder = SqliteRecorder(settings.storage.sqlite_path)
    feature_engine = FeatureEngine(settings.strategy.basis_window)
    strategy = BasisExtremeStrategy(settings.strategy, settings.universe)
    risk_engine = RiskEngine(settings.risk)
    order_manager = OrderManager(settings.execution)
    exchange = DryRunExchangeAdapter()
    run_id = f"dry-{uuid4().hex[:12]}"
    run_started_at = datetime.now(tz=UTC)
    recorder.begin_run(
        RunRecord(
            run_id=run_id,
            mode="dry_run",
            started_at=run_started_at,
            config_path=str(args.config),
            config_snapshot=asdict(settings),
        )
    )

    account = AccountState(
        equity=Decimal("300"),
        realized_pnl_today=Decimal("0"),
        consecutive_losses=0,
        open_positions=[],
    )
    feature_count = 0
    candidate_count = 0
    approved_count = 0
    order_count = 0

    for snapshot in sample_snapshots():
        feature = feature_engine.update(snapshot)
        if feature is None:
            continue
        feature_count += 1
        recorder.record(RecordedEvent("feature", asdict(feature), feature.observed_at))
        candidate = strategy.evaluate(feature)
        if candidate is None:
            recorder.record_signal_journal(
                run_id=run_id,
                feature=feature,
                account_equity=account.equity,
                open_positions_count=len(account.open_positions),
            )
            continue
        candidate_count += 1
        decision = risk_engine.evaluate(candidate, account)
        recorder.record(
            RecordedEvent(
                "decision",
                {"candidate": asdict(candidate), "decision": asdict(decision)},
                candidate.observed_at,
            )
        )
        if not decision.approved:
            recorder.record_signal_journal(
                run_id=run_id,
                feature=feature,
                candidate=candidate,
                decision=decision,
                account_equity=account.equity,
                open_positions_count=len(account.open_positions),
            )
            logger.info(
                "candidate_rejected",
                extra={"event": "candidate_rejected", "extra_fields": {"reason": decision.reason.value}},
            )
            continue
        approved_count += 1
        plan = order_manager.build_plan(candidate, decision)
        recorder.record(RecordedEvent("execution_plan", asdict(plan), candidate.observed_at))
        recorder.record_signal_journal(
            run_id=run_id,
            feature=feature,
            candidate=candidate,
            decision=decision,
            plan=plan,
            account_equity=account.equity,
            open_positions_count=len(account.open_positions),
        )
        for intent in plan.intents:
            ack = __import__("asyncio").run(exchange.place_order(intent))
            recorder.record(RecordedEvent("order_ack", asdict(ack), ack.accepted_at))
            order_count += 1
            logger.info(
                "order_accepted",
                extra={
                    "event": "order_accepted",
                    "extra_fields": {"client_order_id": ack.client_order_id, "symbol": intent.symbol},
                },
            )
    recorder.finish_run(
        run_id,
        ended_at=datetime.now(tz=UTC),
        status="completed",
        metrics={
            "feature_count": feature_count,
            "candidate_count": candidate_count,
            "approved_count": approved_count,
            "order_count": order_count,
        },
    )
    recorder.add_agent_note(
        AgentNote(
            run_id=run_id,
            note_type="run_summary",
            summary="Dry-run completed with structured analysis artifacts",
            details={
                "feature_count": feature_count,
                "candidate_count": candidate_count,
                "approved_count": approved_count,
                "order_count": order_count,
                "analysis_bundle_hint": "Use SqliteRecorder.build_analysis_bundle(run_id) to extract this run.",
            },
            created_at=datetime.now(tz=UTC),
        )
    )
    recorder.close()


if __name__ == "__main__":
    main()
