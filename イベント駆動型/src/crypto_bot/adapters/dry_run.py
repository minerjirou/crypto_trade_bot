from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from crypto_bot.adapters.base import ExchangeAdapter
from crypto_bot.core.models import ExchangeName, OrderAck, OrderIntent, PositionState, UTC


class DryRunExchangeAdapter(ExchangeAdapter):
    def __init__(self) -> None:
        self.orders: list[OrderIntent] = []

    async def connect_public(self) -> None:
        return None

    async def connect_private(self) -> None:
        return None

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        return None

    async def subscribe_orderbook(self, symbols: list[str]) -> None:
        return None

    async def fetch_instruments(self) -> list:
        return []

    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, Decimal]:
        return {}

    async def place_order(self, intent: OrderIntent) -> OrderAck:
        self.orders.append(intent)
        return OrderAck(
            client_order_id=intent.client_order_id,
            exchange_order_id=f"dry-{len(self.orders)}",
            status="accepted",
            accepted_at=datetime.now(tz=UTC),
        )

    async def cancel_all(self) -> None:
        self.orders.clear()

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
