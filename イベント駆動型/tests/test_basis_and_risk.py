from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from crypto_bot.core.events import AgentNote, RunRecord
from crypto_bot.core.config import RiskSettings
from crypto_bot.core.models import ExchangeName, FeatureSnapshot, Instrument, MarketSnapshot, SignalCandidate, SignalSide, UTC
from crypto_bot.features.basis import FeatureEngine
from crypto_bot.risk.engine import AccountState, RiskEngine
from crypto_bot.storage.sqlite import SqliteRecorder


class BasisAndRiskTests(unittest.TestCase):
    def test_feature_engine_emits_zscore(self) -> None:
        instrument = Instrument(
            exchange=ExchangeName.DRY_RUN,
            symbol="ALTUSDT",
            base="ALT",
            quote="USDT",
            spot_symbol="ALTUSDT",
            perp_symbol="ALTUSDT_PERP",
            listing_time=datetime.now(tz=UTC) - timedelta(days=60),
            tick_size=Decimal("0.001"),
            lot_size=Decimal("0.001"),
            min_notional=Decimal("5"),
        )
        engine = FeatureEngine(5)
        result = None
        for perp_mid in ["1.00", "1.01", "1.02"]:
            result = engine.update(
                MarketSnapshot(
                    instrument=instrument,
                    spot_bid=Decimal("0.99"),
                    spot_ask=Decimal("1.01"),
                    perp_bid=Decimal(perp_mid) - Decimal("0.01"),
                    perp_ask=Decimal(perp_mid) + Decimal("0.01"),
                    funding_rate=Decimal("0"),
                    volume_24h_usd=Decimal("1000000"),
                    open_interest_usd=Decimal("800000"),
                    depth_usd_at_5bps=Decimal("25000"),
                    observed_at=datetime.now(tz=UTC),
                )
            )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreater(result.basis_z, Decimal("0"))

    def test_risk_engine_rejects_daily_loss_limit(self) -> None:
        engine = RiskEngine(
            RiskSettings(
                risk_per_trade_pct=Decimal("0.01"),
                max_daily_loss_pct=Decimal("0.04"),
                max_concurrent_positions=2,
                max_leverage=Decimal("3"),
                max_consecutive_losses=3,
            )
        )
        instrument = Instrument(
            exchange=ExchangeName.DRY_RUN,
            symbol="ALTUSDT",
            base="ALT",
            quote="USDT",
            spot_symbol="ALTUSDT",
            perp_symbol="ALTUSDT_PERP",
            listing_time=datetime.now(tz=UTC) - timedelta(days=60),
            tick_size=Decimal("0.001"),
            lot_size=Decimal("0.001"),
            min_notional=Decimal("5"),
        )
        candidate = SignalCandidate(
            instrument=instrument,
            side=SignalSide.LONG,
            score=Decimal("1"),
            basis=Decimal("-0.01"),
            basis_z=Decimal("-2.5"),
            funding_rate=Decimal("0"),
            spread_bps=Decimal("2"),
            entry_price=Decimal("1"),
            stop_price=Decimal("0.95"),
            target_price=Decimal("1.05"),
            max_holding_time=timedelta(hours=1),
            rationale=[],
            observed_at=datetime.now(tz=UTC),
        )
        account = AccountState(
            equity=Decimal("300"),
            realized_pnl_today=Decimal("-20"),
            consecutive_losses=0,
            open_positions=[],
        )
        decision = engine.evaluate(candidate, account)
        self.assertFalse(decision.approved)

    def test_sqlite_recorder_builds_analysis_bundle(self) -> None:
        observed_at = datetime.now(tz=UTC)
        instrument = Instrument(
            exchange=ExchangeName.DRY_RUN,
            symbol="ALTUSDT",
            base="ALT",
            quote="USDT",
            spot_symbol="ALTUSDT",
            perp_symbol="ALTUSDT_PERP",
            listing_time=observed_at - timedelta(days=60),
            tick_size=Decimal("0.001"),
            lot_size=Decimal("0.001"),
            min_notional=Decimal("5"),
        )
        feature = FeatureSnapshot(
            instrument=instrument,
            spot_mid=Decimal("1.0"),
            perp_mid=Decimal("0.97"),
            basis=Decimal("-0.03"),
            basis_z=Decimal("-2.4"),
            funding_rate=Decimal("0.0001"),
            volume_acceleration=Decimal("0.20"),
            oi_acceleration=Decimal("0.10"),
            listing_age_days=60,
            spread_bps=Decimal("4"),
            depth_usd_at_5bps=Decimal("30000"),
            observed_at=observed_at,
        )
        candidate = SignalCandidate(
            instrument=instrument,
            side=SignalSide.LONG,
            score=Decimal("1.5"),
            basis=feature.basis,
            basis_z=feature.basis_z,
            funding_rate=feature.funding_rate,
            spread_bps=feature.spread_bps,
            entry_price=Decimal("0.97"),
            stop_price=Decimal("0.94"),
            target_price=Decimal("1.00"),
            max_holding_time=timedelta(hours=1),
            rationale=["basis_extreme"],
            observed_at=observed_at,
        )

        db_path = Path("test-output") / "recorder-test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            db_path.unlink()
        recorder = SqliteRecorder(db_path)
        try:
            recorder.begin_run(
                RunRecord(
                    run_id="run-1",
                    mode="dry_run",
                    started_at=observed_at,
                    config_path="config/settings.example.yaml",
                    config_snapshot={"storage": {"sqlite_path": Path("data/bot.db")}},
                )
            )
            recorder.record_signal_journal(
                run_id="run-1",
                feature=feature,
                candidate=candidate,
                account_equity=Decimal("300"),
                open_positions_count=0,
            )
            recorder.add_agent_note(
                AgentNote(
                    run_id="run-1",
                    note_type="review",
                    summary="Candidate looked strong",
                    details={"next_action": "review fills"},
                    created_at=observed_at,
                    symbol="ALTUSDT",
                )
            )
            recorder.finish_run(
                "run-1",
                ended_at=observed_at,
                status="completed",
                metrics={"candidate_count": 1},
            )
            bundle = recorder.build_analysis_bundle("run-1")
        finally:
            recorder.close()
            if db_path.exists():
                db_path.unlink()

        assert bundle["run"] is not None
        self.assertEqual(bundle["run"]["metrics_json"]["candidate_count"], 1)
        self.assertEqual(bundle["journal"][0]["symbol"], "ALTUSDT")
        self.assertEqual(bundle["journal"][0]["candidate_json"]["side"], "long")
        self.assertEqual(bundle["notes"][0]["details_json"]["next_action"], "review fills")


if __name__ == "__main__":
    unittest.main()
