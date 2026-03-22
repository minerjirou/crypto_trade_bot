from __future__ import annotations

from dataclasses import dataclass

from crypto_bot.core.models import ExchangeName, Instrument


def normalize_symbol(raw_symbol: str) -> str:
    sanitized = raw_symbol.replace("-", "").replace("_", "").replace("/", "")
    return sanitized.upper()


@dataclass(slots=True)
class SymbolRegistryEntry:
    internal_symbol: str
    exchange: ExchangeName
    spot_symbol: str
    perp_symbol: str


class SymbolRegistry:
    def __init__(self) -> None:
        self._entries: dict[tuple[ExchangeName, str], SymbolRegistryEntry] = {}

    def register(self, instrument: Instrument) -> None:
        internal_symbol = normalize_symbol(instrument.symbol)
        self._entries[(instrument.exchange, internal_symbol)] = SymbolRegistryEntry(
            internal_symbol=internal_symbol,
            exchange=instrument.exchange,
            spot_symbol=instrument.spot_symbol,
            perp_symbol=instrument.perp_symbol,
        )

    def lookup(self, exchange: ExchangeName, raw_symbol: str) -> SymbolRegistryEntry | None:
        return self._entries.get((exchange, normalize_symbol(raw_symbol)))


def common_spot_perp_instruments(instruments: list[Instrument]) -> list[Instrument]:
    result: list[Instrument] = []
    for instrument in instruments:
        if instrument.spot_symbol and instrument.perp_symbol and instrument.enabled:
            result.append(instrument)
    return result
