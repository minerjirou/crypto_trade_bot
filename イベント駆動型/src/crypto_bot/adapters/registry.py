from __future__ import annotations

from crypto_bot.adapters.base import ExchangeAdapter
from crypto_bot.adapters.bitget import BitgetPublicAdapter
from crypto_bot.adapters.dry_run import DryRunExchangeAdapter
from crypto_bot.adapters.mexc import MexcPublicAdapter
from crypto_bot.adapters.paper import PaperExchangeAdapter


def build_adapter(name: str) -> ExchangeAdapter:
    normalized = name.lower()
    if normalized == "dry_run":
        return DryRunExchangeAdapter()
    if normalized == "paper":
        return PaperExchangeAdapter()
    if normalized == "mexc":
        return MexcPublicAdapter()
    if normalized == "bitget":
        return BitgetPublicAdapter()
    raise ValueError(f"unsupported adapter: {name}")
