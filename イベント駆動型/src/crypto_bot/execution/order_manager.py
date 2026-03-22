from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

from crypto_bot.core.config import ExecutionSettings
from crypto_bot.core.models import (
    ExecutionPlan,
    MarketType,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    SignalCandidate,
    SignalSide,
    TimeInForce,
)


@dataclass(slots=True)
class OrderManager:
    settings: ExecutionSettings

    def build_plan(self, candidate: SignalCandidate, decision: RiskDecision) -> ExecutionPlan:
        slice_count = max(1, self.settings.entry_slices)
        slice_quote = (decision.size_quote / Decimal(slice_count)).quantize(Decimal("0.01"))
        intents: list[OrderIntent] = []
        for index in range(slice_count):
            price = self._entry_price(candidate, index, slice_count)
            size = (slice_quote / price).quantize(candidate.instrument.lot_size, rounding=ROUND_DOWN)
            intents.append(
                OrderIntent(
                    exchange=candidate.instrument.exchange,
                    symbol=candidate.instrument.perp_symbol,
                    market_type=MarketType.PERP,
                    side=OrderSide.BUY if candidate.side is SignalSide.LONG else OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    price=price,
                    size=size,
                    reduce_only=False,
                    post_only=self.settings.prefer_post_only,
                    time_in_force=TimeInForce.GTC,
                    ttl_seconds=self.settings.order_ttl_seconds,
                    client_order_id=f"{candidate.instrument.symbol}-{index}-{uuid4().hex[:10]}",
                    meta={"score": str(candidate.score), "basis_z": str(candidate.basis_z)},
                )
            )
        return ExecutionPlan(
            candidate=candidate,
            intents=intents,
            emergency_close_allowed=self.settings.emergency_taker_close,
        )

    @staticmethod
    def _entry_price(candidate: SignalCandidate, index: int, slice_count: int) -> Decimal:
        step = Decimal(index) / Decimal(max(1, slice_count))
        offset = Decimal("0.0005") * step
        if candidate.side is SignalSide.LONG:
            return candidate.entry_price * (Decimal("1") - offset)
        return candidate.entry_price * (Decimal("1") + offset)
