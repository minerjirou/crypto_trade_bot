from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


UTC = timezone.utc


class ExchangeName(str, Enum):
    MEXC = "mexc"
    BITGET = "bitget"
    BYBIT = "bybit"
    OKX = "okx"
    GATE = "gate"
    COINEX = "coinex"
    HYPERLIQUID = "hyperliquid"
    DEXSCREENER = "dexscreener"
    DRY_RUN = "dry_run"
    PAPER = "paper"


class MarketType(str, Enum):
    SPOT = "spot"
    PERP = "perp"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class TimeInForce(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class OrderStatus(str, Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class SignalSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class DecisionReason(str, Enum):
    APPROVED = "approved"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_CONCURRENT_POSITIONS = "max_concurrent_positions"
    CONSECUTIVE_LOSS_LIMIT = "consecutive_loss_limit"
    KILL_SWITCH = "kill_switch"
    BELOW_MIN_NOTIONAL = "below_min_notional"
    SYMBOL_ALREADY_OPEN = "symbol_already_open"


class ExitReason(str, Enum):
    BASIS_MEAN_REVERSION = "basis_mean_reversion"
    TARGET = "target"
    STOP = "stop"
    TIMEOUT = "timeout"
    THESIS_BROKEN = "thesis_broken"
    EMERGENCY = "emergency"


@dataclass(slots=True)
class Instrument:
    exchange: ExchangeName
    symbol: str
    base: str
    quote: str
    spot_symbol: str
    perp_symbol: str
    listing_time: datetime
    tick_size: Decimal
    lot_size: Decimal
    min_notional: Decimal
    enabled: bool = True

    @property
    def listing_age_days(self) -> int:
        return max(0, (datetime.now(tz=UTC) - self.listing_time).days)


@dataclass(slots=True)
class OrderBookTop:
    bid_price: Decimal
    bid_size: Decimal
    ask_price: Decimal
    ask_size: Decimal
    observed_at: datetime


@dataclass(slots=True)
class FundingSnapshot:
    instrument: Instrument
    funding_rate: Decimal
    next_funding_at: datetime | None
    observed_at: datetime


@dataclass(slots=True)
class MarketSnapshot:
    instrument: Instrument
    spot_bid: Decimal
    spot_ask: Decimal
    perp_bid: Decimal
    perp_ask: Decimal
    funding_rate: Decimal
    volume_24h_usd: Decimal
    open_interest_usd: Decimal
    depth_usd_at_5bps: Decimal
    observed_at: datetime
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def spot_mid(self) -> Decimal:
        return (self.spot_bid + self.spot_ask) / Decimal("2")

    @property
    def perp_mid(self) -> Decimal:
        return (self.perp_bid + self.perp_ask) / Decimal("2")

    @property
    def spread_bps(self) -> Decimal:
        if self.spot_mid == 0:
            return Decimal("0")
        return ((self.spot_ask - self.spot_bid) / self.spot_mid) * Decimal("10000")


@dataclass(slots=True)
class FeatureSnapshot:
    instrument: Instrument
    spot_mid: Decimal
    perp_mid: Decimal
    basis: Decimal
    basis_z: Decimal
    funding_rate: Decimal
    volume_acceleration: Decimal
    oi_acceleration: Decimal
    listing_age_days: int
    spread_bps: Decimal
    depth_usd_at_5bps: Decimal
    observed_at: datetime


@dataclass(slots=True)
class SignalCandidate:
    instrument: Instrument
    side: SignalSide
    score: Decimal
    basis: Decimal
    basis_z: Decimal
    funding_rate: Decimal
    spread_bps: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    max_holding_time: timedelta
    rationale: list[str]
    observed_at: datetime


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reason: DecisionReason
    size_quote: Decimal
    leverage: Decimal
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OrderIntent:
    exchange: ExchangeName
    symbol: str
    market_type: MarketType
    side: OrderSide
    order_type: OrderType
    price: Decimal
    size: Decimal
    reduce_only: bool
    post_only: bool
    time_in_force: TimeInForce
    ttl_seconds: int
    client_order_id: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionPlan:
    candidate: SignalCandidate
    intents: list[OrderIntent]
    emergency_close_allowed: bool


@dataclass(slots=True)
class OrderAck:
    client_order_id: str
    exchange_order_id: str
    status: str
    accepted_at: datetime


@dataclass(slots=True)
class OrderState:
    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: OrderSide
    price: Decimal
    size: Decimal
    status: OrderStatus
    reduce_only: bool
    post_only: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class AmendRequest:
    client_order_id: str
    new_price: Decimal | None = None
    new_size: Decimal | None = None


@dataclass(slots=True)
class CancelRequest:
    client_order_id: str


@dataclass(slots=True)
class CancelAck:
    client_order_id: str
    status: str
    canceled_at: datetime


@dataclass(slots=True)
class FillEvent:
    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: OrderSide
    fill_price: Decimal
    fill_size: Decimal
    fee_paid: Decimal
    liquidity: str
    filled_at: datetime
    reduce_only: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PositionState:
    exchange: ExchangeName
    symbol: str
    side: SignalSide
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    opened_at: datetime


@dataclass(slots=True)
class TradeState:
    exchange: ExchangeName
    symbol: str
    side: SignalSide
    size: Decimal
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    opened_at: datetime
    max_hold_until: datetime
    entry_fees_paid: Decimal = Decimal("0")


@dataclass(slots=True)
class TradeOutcome:
    symbol: str
    side: SignalSide
    entry_price: Decimal
    exit_price: Decimal
    size: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    entry_fees_paid: Decimal
    exit_fees_paid: Decimal
    exit_reason: ExitReason
    opened_at: datetime
    closed_at: datetime
    holding_seconds: int


@dataclass(slots=True)
class PnLSnapshot:
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    fees_paid: Decimal
    recorded_at: datetime
