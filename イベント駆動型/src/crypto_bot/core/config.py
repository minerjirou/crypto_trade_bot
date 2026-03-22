from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class AppSettings:
    env: str
    timezone: str
    dry_run: bool
    paper_mode: bool
    live_trading: bool


@dataclass(slots=True)
class UniverseSettings:
    exchanges: list[str]
    max_symbols_per_exchange: int
    include_only_common_spot_perp: bool
    min_listing_age_days: int
    max_listing_age_days: int
    min_24h_volume_usd: Decimal
    max_spread_bps: Decimal


@dataclass(slots=True)
class StrategySettings:
    name: str
    basis_window: int
    entry_z_abs: Decimal
    exit_z_abs: Decimal
    max_hold_minutes: int
    use_funding_filter: bool
    funding_block_long_above: Decimal
    funding_block_short_below: Decimal


@dataclass(slots=True)
class RiskSettings:
    risk_per_trade_pct: Decimal
    max_daily_loss_pct: Decimal
    max_concurrent_positions: int
    max_leverage: Decimal
    max_consecutive_losses: int


@dataclass(slots=True)
class ExecutionSettings:
    prefer_post_only: bool
    entry_slices: int
    order_ttl_seconds: int
    emergency_taker_close: bool
    cancel_all_on_disconnect: bool


@dataclass(slots=True)
class StorageSettings:
    sqlite_path: Path
    export_dir: Path


@dataclass(slots=True)
class Settings:
    app: AppSettings
    universe: UniverseSettings
    strategy: StrategySettings
    risk: RiskSettings
    execution: ExecutionSettings
    storage: StorageSettings
    fees: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "Settings":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            app=AppSettings(**raw["app"]),
            universe=UniverseSettings(
                exchanges=list(raw["universe"]["exchanges"]),
                max_symbols_per_exchange=int(raw["universe"]["max_symbols_per_exchange"]),
                include_only_common_spot_perp=bool(raw["universe"]["include_only_common_spot_perp"]),
                min_listing_age_days=int(raw["universe"]["min_listing_age_days"]),
                max_listing_age_days=int(raw["universe"]["max_listing_age_days"]),
                min_24h_volume_usd=Decimal(str(raw["universe"]["min_24h_volume_usd"])),
                max_spread_bps=Decimal(str(raw["universe"]["max_spread_bps"])),
            ),
            strategy=StrategySettings(
                name=str(raw["strategy"]["name"]),
                basis_window=int(raw["strategy"]["basis_window"]),
                entry_z_abs=Decimal(str(raw["strategy"]["entry_z_abs"])),
                exit_z_abs=Decimal(str(raw["strategy"]["exit_z_abs"])),
                max_hold_minutes=int(raw["strategy"]["max_hold_minutes"]),
                use_funding_filter=bool(raw["strategy"]["use_funding_filter"]),
                funding_block_long_above=Decimal(str(raw["strategy"]["funding_block_long_above"])),
                funding_block_short_below=Decimal(str(raw["strategy"]["funding_block_short_below"])),
            ),
            risk=RiskSettings(
                risk_per_trade_pct=Decimal(str(raw["risk"]["risk_per_trade_pct"])),
                max_daily_loss_pct=Decimal(str(raw["risk"]["max_daily_loss_pct"])),
                max_concurrent_positions=int(raw["risk"]["max_concurrent_positions"]),
                max_leverage=Decimal(str(raw["risk"]["max_leverage"])),
                max_consecutive_losses=int(raw["risk"]["max_consecutive_losses"]),
            ),
            execution=ExecutionSettings(**raw["execution"]),
            storage=StorageSettings(
                sqlite_path=Path(raw["storage"]["sqlite_path"]),
                export_dir=Path(raw["storage"]["export_dir"]),
            ),
            fees=dict(raw["fees"]),
        )
