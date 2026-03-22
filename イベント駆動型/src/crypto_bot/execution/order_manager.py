from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

from crypto_bot.core.config import ExecutionSettings
from crypto_bot.core.models import (
    ExitReason,
    ExecutionPlan,
    MarketType,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    SignalCandidate,
    SignalSide,
    TimeInForce,
    TradeState,
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

    def build_close_intent(
        self,
        trade: TradeState,
        mark_price: Decimal,
        reason: ExitReason,
    ) -> OrderIntent:
        use_market = reason is ExitReason.EMERGENCY and self.settings.emergency_taker_close
        side = OrderSide.SELL if trade.side is SignalSide.LONG else OrderSide.BUY
        price = self._protective_exit_price(trade.side, mark_price)
        return OrderIntent(
            exchange=trade.exchange,
            symbol=trade.symbol,
            market_type=MarketType.PERP,
            side=side,
            order_type=OrderType.MARKET if use_market else OrderType.LIMIT,
            price=mark_price if use_market else price,
            size=trade.size,
            reduce_only=True,
            post_only=False if use_market else self.settings.prefer_post_only,
            time_in_force=TimeInForce.IOC if use_market else TimeInForce.GTC,
            ttl_seconds=self.settings.order_ttl_seconds,
            client_order_id=f"{trade.symbol}-close-{uuid4().hex[:10]}",
            meta={"exit_reason": reason.value},
        )

    def amend_price(self, existing_price: Decimal, side: OrderSide, tick_size: Decimal) -> Decimal:
        offset = tick_size * Decimal("1")
        return existing_price - offset if side is OrderSide.BUY else existing_price + offset

    @staticmethod
    def _entry_price(candidate: SignalCandidate, index: int, slice_count: int) -> Decimal:
        step = Decimal(index) / Decimal(max(1, slice_count))
        offset = Decimal("0.0005") * step
        if candidate.side is SignalSide.LONG:
            return candidate.entry_price * (Decimal("1") - offset)
        return candidate.entry_price * (Decimal("1") + offset)

    @staticmethod
    def _protective_exit_price(side: SignalSide, mark_price: Decimal) -> Decimal:
        offset = Decimal("0.0005")
        if side is SignalSide.LONG:
            return mark_price * (Decimal("1") + offset)
        return mark_price * (Decimal("1") - offset)
