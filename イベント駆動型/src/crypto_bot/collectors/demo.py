from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from crypto_bot.core.models import ExchangeName, Instrument, MarketSnapshot, UTC


def demo_instrument(exchange: ExchangeName = ExchangeName.PAPER, symbol: str = "ALTUSDT") -> Instrument:
    base = symbol.removesuffix("USDT")
    return Instrument(
        exchange=exchange,
        symbol=symbol,
        base=base,
        quote="USDT",
        spot_symbol=symbol,
        perp_symbol=f"{symbol}_PERP",
        listing_time=datetime.now(tz=UTC) - timedelta(days=90),
        tick_size=Decimal("0.001"),
        lot_size=Decimal("0.001"),
        min_notional=Decimal("5"),
    )


def generate_demo_snapshots(
    exchange: ExchangeName = ExchangeName.PAPER,
    symbol: str = "ALTUSDT",
) -> list[MarketSnapshot]:
    instrument = demo_instrument(exchange=exchange, symbol=symbol)
    base_spot = Decimal("1.0000")
    perp_path = [
        Decimal("1.000"),
        Decimal("1.002"),
        Decimal("0.998"),
        Decimal("0.992"),
        Decimal("0.970"),
        Decimal("0.900"),
        Decimal("0.820"),
        Decimal("0.860"),
        Decimal("0.910"),
        Decimal("0.955"),
        Decimal("0.990"),
        Decimal("1.000"),
    ]
    snapshots: list[MarketSnapshot] = []
    for index, perp_mid in enumerate(perp_path):
        spot_mid = base_spot + (Decimal(index % 3) - Decimal("1")) * Decimal("0.0005")
        snapshots.append(
            MarketSnapshot(
                instrument=instrument,
                spot_bid=spot_mid - Decimal("0.0005"),
                spot_ask=spot_mid + Decimal("0.0005"),
                perp_bid=perp_mid - Decimal("0.0010"),
                perp_ask=perp_mid + Decimal("0.0010"),
                funding_rate=Decimal("0.0001"),
                volume_24h_usd=Decimal("1200000") + Decimal(index * 75000),
                open_interest_usd=Decimal("900000") + Decimal(index * 50000),
                depth_usd_at_5bps=Decimal("35000") + Decimal(index * 1000),
                observed_at=datetime.now(tz=UTC) + timedelta(minutes=index),
                meta={"source": "demo"},
            )
        )
    return snapshots
