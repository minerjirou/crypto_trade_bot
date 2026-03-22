from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from crypto_bot.adapters.base import ExchangeAdapter
from crypto_bot.collectors.demo import demo_instrument
from crypto_bot.core.models import (
    AmendRequest,
    CancelAck,
    CancelRequest,
    ExchangeName,
    Instrument,
    MarketSnapshot,
    OrderAck,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderStatus,
    PositionState,
    UTC,
)


class DryRunExchangeAdapter(ExchangeAdapter):
    def __init__(self) -> None:
        self.orders: list[OrderIntent] = []
        self._order_states: dict[str, OrderState] = {}
        self._snapshot: MarketSnapshot | None = None

    def set_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        self._snapshot = snapshot

    async def connect_public(self) -> None:
        return None

    async def connect_private(self) -> None:
        return None

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        return None

    async def subscribe_orderbook(self, symbols: list[str]) -> None:
        return None

    async def fetch_instruments(self) -> list[Instrument]:
        return [demo_instrument(exchange=ExchangeName.DRY_RUN)]

    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, Decimal]:
        return {symbol: Decimal("0") for symbol in symbols}

    async def fetch_market_snapshot(self, instrument: Instrument) -> MarketSnapshot | None:
        if self._snapshot and self._snapshot.instrument.symbol == instrument.symbol:
            return self._snapshot
        return None

    async def place_order(self, intent: OrderIntent) -> OrderAck:
        self.orders.append(intent)
        now = datetime.now(tz=UTC)
        self._order_states[intent.client_order_id] = OrderState(
            client_order_id=intent.client_order_id,
            exchange_order_id=f"dry-{len(self.orders)}",
            symbol=intent.symbol,
            side=intent.side,
            price=intent.price,
            size=intent.size,
            status=OrderStatus.ACCEPTED,
            reduce_only=intent.reduce_only,
            post_only=intent.post_only,
            created_at=now,
            updated_at=now,
        )
        return OrderAck(
            client_order_id=intent.client_order_id,
            exchange_order_id=f"dry-{len(self.orders)}",
            status="accepted",
            accepted_at=now,
        )

    async def amend_order(self, req: AmendRequest) -> OrderAck:
        state = self._order_states[req.client_order_id]
        if req.new_price is not None:
            state.price = req.new_price
        if req.new_size is not None:
            state.size = req.new_size
        state.updated_at = datetime.now(tz=UTC)
        return OrderAck(
            client_order_id=state.client_order_id,
            exchange_order_id=state.exchange_order_id,
            status=OrderStatus.ACCEPTED.value,
            accepted_at=state.updated_at,
        )

    async def cancel_order(self, req: CancelRequest) -> CancelAck:
        state = self._order_states[req.client_order_id]
        state.status = OrderStatus.CANCELED
        state.updated_at = datetime.now(tz=UTC)
        return CancelAck(
            client_order_id=req.client_order_id,
            status=OrderStatus.CANCELED.value,
            canceled_at=state.updated_at,
        )

    async def fetch_open_orders(self) -> list[OrderState]:
        return list(self._order_states.values())

    async def cancel_all(self) -> None:
        self.orders.clear()
        for state in self._order_states.values():
            state.status = OrderStatus.CANCELED

    async def fetch_positions(self) -> list[PositionState]:
        return [
            PositionState(
                exchange=ExchangeName.DRY_RUN,
                symbol=order.symbol,
                side=self._to_signal_side(order.side.value),
                size=order.size,
                entry_price=order.price,
                mark_price=order.price,
                unrealized_pnl=Decimal("0"),
                opened_at=datetime.now(tz=UTC),
            )
            for order in self.orders
        ]

    @staticmethod
    def _to_signal_side(side: str):
        from crypto_bot.core.models import SignalSide

        return SignalSide.LONG if side == "buy" else SignalSide.SHORT
