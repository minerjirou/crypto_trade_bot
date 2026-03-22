from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from crypto_bot.adapters.base import ExchangeAdapter
from crypto_bot.core.config import Settings
from crypto_bot.core.events import AgentNote, RecordedEvent, RunRecord
from crypto_bot.core.models import (
    ExitReason,
    FillEvent,
    MarketSnapshot,
    PnLSnapshot,
    PositionState,
    SignalCandidate,
    SignalSide,
    TradeOutcome,
    TradeState,
    UTC,
)
from crypto_bot.execution.order_manager import OrderManager
from crypto_bot.features.basis import FeatureEngine
from crypto_bot.risk.engine import AccountState, RiskEngine
from crypto_bot.storage.sqlite import SqliteRecorder
from crypto_bot.strategies.basis_extreme import BasisExtremeStrategy


@dataclass(slots=True)
class RunResult:
    run_id: str
    mode: str
    metrics: dict[str, int | str]


class TradingSession:
    def __init__(
        self,
        *,
        settings: Settings,
        recorder: SqliteRecorder,
        adapter: ExchangeAdapter,
        mode: str,
    ) -> None:
        self._settings = settings
        self._recorder = recorder
        self._adapter = adapter
        self._mode = mode
        self._feature_engine = FeatureEngine(settings.strategy.basis_window)
        self._strategy = BasisExtremeStrategy(settings.strategy, settings.universe)
        self._risk_engine = RiskEngine(settings.risk)
        self._order_manager = OrderManager(settings.execution)
        self._account = AccountState(
            equity=Decimal("300"),
            realized_pnl_today=Decimal("0"),
            consecutive_losses=0,
            open_positions=[],
        )
        self._active_trades: dict[str, TradeState] = {}
        self._last_marks: dict[str, Decimal] = {}
        self._total_fees_paid = Decimal("0")
        self._metrics: dict[str, int] = {
            "feature_count": 0,
            "candidate_count": 0,
            "approved_count": 0,
            "order_count": 0,
            "fill_count": 0,
            "exit_count": 0,
        }

    async def run_snapshots(self, snapshots: list[MarketSnapshot], config_path: Path) -> RunResult:
        run_id = f"{self._mode}-{uuid4().hex[:12]}"
        started_at = datetime.now(tz=UTC)
        self._recorder.begin_run(
            RunRecord(
                run_id=run_id,
                mode=self._mode,
                started_at=started_at,
                config_path=str(config_path),
                config_snapshot=asdict(self._settings),
            )
        )
        for snapshot in snapshots:
            await self._process_snapshot(run_id, snapshot)
        self._refresh_account_snapshots(run_id, datetime.now(tz=UTC))
        self._recorder.finish_run(
            run_id,
            ended_at=datetime.now(tz=UTC),
            status="completed",
            metrics={
                **self._metrics,
                "active_trade_count": len(self._active_trades),
                "final_equity": str(self._account.equity),
            },
        )
        self._recorder.add_agent_note(
            AgentNote(
                run_id=run_id,
                note_type="run_summary",
                summary=f"{self._mode} completed with structured trade artifacts",
                details={
                    **self._metrics,
                    "final_equity": str(self._account.equity),
                    "analysis_bundle_hint": "Use SqliteRecorder.build_analysis_bundle(run_id).",
                },
                created_at=datetime.now(tz=UTC),
            )
        )
        return RunResult(run_id=run_id, mode=self._mode, metrics={**self._metrics, "final_equity": str(self._account.equity)})

    async def _process_snapshot(self, run_id: str, snapshot: MarketSnapshot) -> None:
        self._last_marks[snapshot.instrument.perp_symbol] = snapshot.perp_mid
        if hasattr(self._adapter, "set_market_snapshot"):
            getattr(self._adapter, "set_market_snapshot")(snapshot)
        feature = self._feature_engine.update(snapshot)
        if feature is None:
            return
        self._metrics["feature_count"] += 1
        self._recorder.record(RecordedEvent("feature", asdict(feature), feature.observed_at))
        await self._maybe_exit_trade(run_id, feature)
        if feature.instrument.perp_symbol in self._active_trades:
            self._recorder.record_signal_journal(
                run_id=run_id,
                feature=feature,
                account_equity=self._account.equity,
                open_positions_count=len(self._account.open_positions),
            )
            self._refresh_account_snapshots(run_id, feature.observed_at)
            return
        candidate = self._strategy.evaluate(feature)
        if candidate is None:
            self._recorder.record_signal_journal(
                run_id=run_id,
                feature=feature,
                account_equity=self._account.equity,
                open_positions_count=len(self._account.open_positions),
            )
            self._refresh_account_snapshots(run_id, feature.observed_at)
            return
        self._metrics["candidate_count"] += 1
        decision = self._risk_engine.evaluate(candidate, self._account)
        self._recorder.record(
            RecordedEvent(
                "decision",
                {"candidate": asdict(candidate), "decision": asdict(decision)},
                candidate.observed_at,
            )
        )
        plan = None
        if decision.approved:
            self._metrics["approved_count"] += 1
            plan = self._order_manager.build_plan(candidate, decision)
            self._recorder.record(RecordedEvent("execution_plan", asdict(plan), candidate.observed_at))
            await self._execute_entry_plan(run_id, candidate, plan)
        self._recorder.record_signal_journal(
            run_id=run_id,
            feature=feature,
            candidate=candidate,
            decision=decision,
            plan=plan,
            account_equity=self._account.equity,
            open_positions_count=len(self._account.open_positions),
        )
        self._refresh_account_snapshots(run_id, feature.observed_at)

    async def _execute_entry_plan(self, run_id: str, candidate: SignalCandidate, plan) -> None:
        fills: list[FillEvent] = []
        for intent in plan.intents:
            ack = await self._adapter.place_order(intent)
            self._metrics["order_count"] += 1
            self._recorder.record(RecordedEvent("order_ack", asdict(ack), ack.accepted_at))
            self._recorder.record_order_ack(
                run_id=run_id,
                symbol=candidate.instrument.symbol,
                ack=ack,
                intent=intent,
            )
            fills.extend(self._drain_fills(run_id))
        if fills:
            trade = self._build_trade_state(candidate, fills)
            self._active_trades[trade.symbol] = trade
            self._account.fees_paid_today += trade.entry_fees_paid
            self._total_fees_paid += trade.entry_fees_paid
            self._refresh_open_positions()

    async def _maybe_exit_trade(self, run_id: str, feature) -> None:
        trade = self._active_trades.get(feature.instrument.perp_symbol)
        if trade is None:
            return
        reason = self._determine_exit_reason(trade, feature)
        if reason is None:
            return
        intent = self._order_manager.build_close_intent(trade, feature.perp_mid, reason)
        ack = await self._adapter.place_order(intent)
        self._metrics["order_count"] += 1
        self._recorder.record(RecordedEvent("order_ack", asdict(ack), ack.accepted_at))
        self._recorder.record_order_ack(
            run_id=run_id,
            symbol=feature.instrument.symbol,
            ack=ack,
            intent=intent,
        )
        fills = self._drain_fills(run_id)
        if not fills:
            return
        outcome = self._close_trade(trade, fills, reason)
        self._metrics["exit_count"] += 1
        self._recorder.record_trade_outcome(run_id=run_id, outcome=outcome)
        self._account.realized_pnl_today += outcome.net_pnl
        self._account.equity += outcome.net_pnl
        self._account.fees_paid_today += outcome.exit_fees_paid
        self._total_fees_paid += outcome.exit_fees_paid
        self._account.consecutive_losses = self._account.consecutive_losses + 1 if outcome.net_pnl < 0 else 0
        self._active_trades.pop(trade.symbol, None)
        self._refresh_open_positions()

    def _drain_fills(self, run_id: str) -> list[FillEvent]:
        if not hasattr(self._adapter, "drain_fills"):
            return []
        fills = list(getattr(self._adapter, "drain_fills")())
        for fill in fills:
            self._metrics["fill_count"] += 1
            self._recorder.record(RecordedEvent("fill", asdict(fill), fill.filled_at))
            self._recorder.record_fill(run_id=run_id, fill=fill)
        return fills

    def _build_trade_state(self, candidate: SignalCandidate, fills: list[FillEvent]) -> TradeState:
        total_size = sum((fill.fill_size for fill in fills), start=Decimal("0"))
        weighted_entry = sum((fill.fill_price * fill.fill_size for fill in fills), start=Decimal("0")) / total_size
        entry_fees = sum((fill.fee_paid for fill in fills), start=Decimal("0"))
        return TradeState(
            exchange=candidate.instrument.exchange,
            symbol=candidate.instrument.perp_symbol,
            side=candidate.side,
            size=total_size,
            entry_price=weighted_entry,
            stop_price=candidate.stop_price,
            target_price=candidate.target_price,
            opened_at=fills[0].filled_at,
            max_hold_until=fills[0].filled_at + candidate.max_holding_time,
            entry_fees_paid=entry_fees,
        )

    def _determine_exit_reason(self, trade: TradeState, feature) -> ExitReason | None:
        current_price = feature.perp_mid
        if feature.observed_at >= trade.max_hold_until:
            return ExitReason.TIMEOUT
        if trade.side is SignalSide.LONG:
            if current_price <= trade.stop_price:
                return ExitReason.STOP
            if current_price >= trade.target_price:
                return ExitReason.TARGET
        else:
            if current_price >= trade.stop_price:
                return ExitReason.STOP
            if current_price <= trade.target_price:
                return ExitReason.TARGET
        if abs(feature.basis_z) <= self._settings.strategy.exit_z_abs:
            return ExitReason.BASIS_MEAN_REVERSION
        return None

    def _close_trade(self, trade: TradeState, fills: list[FillEvent], reason: ExitReason) -> TradeOutcome:
        total_size = sum((fill.fill_size for fill in fills), start=Decimal("0"))
        weighted_exit = sum((fill.fill_price * fill.fill_size for fill in fills), start=Decimal("0")) / total_size
        exit_fees = sum((fill.fee_paid for fill in fills), start=Decimal("0"))
        direction = Decimal("1") if trade.side is SignalSide.LONG else Decimal("-1")
        gross_pnl = (weighted_exit - trade.entry_price) * trade.size * direction
        net_pnl = gross_pnl - trade.entry_fees_paid - exit_fees
        closed_at = fills[-1].filled_at
        return TradeOutcome(
            symbol=trade.symbol,
            side=trade.side,
            entry_price=trade.entry_price,
            exit_price=weighted_exit,
            size=trade.size,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            entry_fees_paid=trade.entry_fees_paid,
            exit_fees_paid=exit_fees,
            exit_reason=reason,
            opened_at=trade.opened_at,
            closed_at=closed_at,
            holding_seconds=int((closed_at - trade.opened_at).total_seconds()),
        )

    def _refresh_open_positions(self) -> None:
        positions: list[PositionState] = []
        for trade in self._active_trades.values():
            mark_price = self._last_marks.get(trade.symbol, trade.entry_price)
            direction = Decimal("1") if trade.side is SignalSide.LONG else Decimal("-1")
            unrealized = (mark_price - trade.entry_price) * trade.size * direction
            positions.append(
                PositionState(
                    exchange=trade.exchange,
                    symbol=trade.symbol,
                    side=trade.side,
                    size=trade.size,
                    entry_price=trade.entry_price,
                    mark_price=mark_price,
                    unrealized_pnl=unrealized,
                    opened_at=trade.opened_at,
                )
            )
        self._account.open_positions = positions

    def _refresh_account_snapshots(self, run_id: str, recorded_at: datetime) -> None:
        self._refresh_open_positions()
        unrealized_total = Decimal("0")
        for position in self._account.open_positions:
            unrealized_total += position.unrealized_pnl
            self._recorder.record_position_snapshot(run_id=run_id, position=position, recorded_at=recorded_at)
        self._recorder.record_pnl_snapshot(
            run_id=run_id,
            pnl=PnLSnapshot(
                realized_pnl=self._account.realized_pnl_today,
                unrealized_pnl=unrealized_total,
                fees_paid=self._total_fees_paid,
                recorded_at=recorded_at,
            ),
        )
