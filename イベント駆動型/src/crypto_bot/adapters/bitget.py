from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from crypto_bot.adapters.base import ExchangeAdapter
from crypto_bot.core.models import ExchangeName, Instrument, OrderAck, OrderIntent, PositionState, UTC


class BitgetPublicAdapter(ExchangeAdapter):
    async def connect_public(self) -> None:
        return None

    async def connect_private(self) -> None:
        raise NotImplementedError("private API is disabled for MVP")

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        return None

    async def subscribe_orderbook(self, symbols: list[str]) -> None:
        return None

    async def fetch_instruments(self) -> list[Instrument]:
        return [
            Instrument(
                exchange=ExchangeName.BITGET,
                symbol="BTCUSDT",
                base="BTC",
                quote="USDT",
                spot_symbol="BTCUSDT",
                perp_symbol="BTCUSDT_UMCBL",
                listing_time=datetime(2024, 1, 1, tzinfo=UTC),
                tick_size=Decimal("0.1"),
                lot_size=Decimal("0.001"),
                min_notional=Decimal("5"),
            )
        ]

    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, Decimal]:
        return {symbol: Decimal("0.001") for symbol in symbols}

    async def place_order(self, intent: OrderIntent) -> OrderAck:
        raise NotImplementedError("use dry-run or paper adapter before live trading")

    async def cancel_all(self) -> None:
        raise NotImplementedError

    async def fetch_positions(self) -> list[PositionState]:
        return []
