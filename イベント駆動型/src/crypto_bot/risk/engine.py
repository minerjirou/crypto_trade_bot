from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from crypto_bot.core.config import RiskSettings
from crypto_bot.core.models import DecisionReason, PositionState, RiskDecision, SignalCandidate


@dataclass(slots=True)
class AccountState:
    equity: Decimal
    realized_pnl_today: Decimal
    consecutive_losses: int
    open_positions: list[PositionState]
    fees_paid_today: Decimal = Decimal("0")
    kill_switch_active: bool = False


class RiskEngine:
    def __init__(self, settings: RiskSettings) -> None:
        self._settings = settings

    def evaluate(self, candidate: SignalCandidate, account: AccountState) -> RiskDecision:
        if account.kill_switch_active:
            return RiskDecision(False, DecisionReason.KILL_SWITCH, Decimal("0"), Decimal("0"))
        if any(position.symbol == candidate.instrument.perp_symbol for position in account.open_positions):
            return RiskDecision(False, DecisionReason.SYMBOL_ALREADY_OPEN, Decimal("0"), Decimal("0"))
        if len(account.open_positions) >= self._settings.max_concurrent_positions:
            return RiskDecision(False, DecisionReason.MAX_CONCURRENT_POSITIONS, Decimal("0"), Decimal("0"))
        if account.consecutive_losses >= self._settings.max_consecutive_losses:
            return RiskDecision(False, DecisionReason.CONSECUTIVE_LOSS_LIMIT, Decimal("0"), Decimal("0"))
        daily_loss_limit = account.equity * self._settings.max_daily_loss_pct
        if abs(account.realized_pnl_today) >= daily_loss_limit and account.realized_pnl_today < 0:
            return RiskDecision(False, DecisionReason.DAILY_LOSS_LIMIT, Decimal("0"), Decimal("0"))
        stop_distance = abs(candidate.entry_price - candidate.stop_price)
        if stop_distance <= 0:
            return RiskDecision(False, DecisionReason.BELOW_MIN_NOTIONAL, Decimal("0"), Decimal("0"))
        risk_budget = account.equity * self._settings.risk_per_trade_pct
        size_base = (risk_budget / stop_distance).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        size_quote = (size_base * candidate.entry_price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if size_quote < candidate.instrument.min_notional:
            return RiskDecision(False, DecisionReason.BELOW_MIN_NOTIONAL, Decimal("0"), Decimal("0"))
        leverage = min(self._settings.max_leverage, Decimal("1") + abs(candidate.basis_z))
        return RiskDecision(True, DecisionReason.APPROVED, size_quote, leverage)
