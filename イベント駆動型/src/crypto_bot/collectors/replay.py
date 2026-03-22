from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from crypto_bot.core.models import ExchangeName, Instrument, MarketSnapshot, UTC


def load_replay_snapshots(path: Path) -> list[MarketSnapshot]:
    snapshots: list[MarketSnapshot] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        exchange = ExchangeName(payload.get("exchange", ExchangeName.PAPER.value))
        instrument = Instrument(
            exchange=exchange,
            symbol=str(payload["symbol"]),
            base=str(payload.get("base", str(payload["symbol"]).removesuffix("USDT"))),
            quote=str(payload.get("quote", "USDT")),
            spot_symbol=str(payload.get("spot_symbol", payload["symbol"])),
            perp_symbol=str(payload.get("perp_symbol", f"{payload['symbol']}_PERP")),
            listing_time=datetime.fromisoformat(payload.get("listing_time", datetime.now(tz=UTC).isoformat())),
            tick_size=Decimal(str(payload.get("tick_size", "0.001"))),
            lot_size=Decimal(str(payload.get("lot_size", "0.001"))),
            min_notional=Decimal(str(payload.get("min_notional", "5"))),
        )
        snapshots.append(
            MarketSnapshot(
                instrument=instrument,
                spot_bid=Decimal(str(payload["spot_bid"])),
                spot_ask=Decimal(str(payload["spot_ask"])),
                perp_bid=Decimal(str(payload["perp_bid"])),
                perp_ask=Decimal(str(payload["perp_ask"])),
                funding_rate=Decimal(str(payload.get("funding_rate", "0"))),
                volume_24h_usd=Decimal(str(payload.get("volume_24h_usd", "0"))),
                open_interest_usd=Decimal(str(payload.get("open_interest_usd", "0"))),
                depth_usd_at_5bps=Decimal(str(payload.get("depth_usd_at_5bps", "0"))),
                observed_at=datetime.fromisoformat(payload["observed_at"]),
                meta=dict(payload.get("meta", {})),
            )
        )
    return snapshots
