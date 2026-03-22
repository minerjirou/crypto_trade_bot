from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crypto_bot.adapters.base import ExchangeAdapter
from crypto_bot.core.models import (
    AmendRequest,
    CancelAck,
    CancelRequest,
    ExchangeName,
    FillEvent,
    Instrument,
    MarketSnapshot,
    OrderAck,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderStatus,
    PositionState,
    SignalSide,
    UTC,
)


@dataclass(slots=True)
class _PaperPosition:
    symbol: str
    side: SignalSide
    size: Decimal
    entry_price: Decimal
    opened_at: datetime


class PaperExchangeAdapter(ExchangeAdapter):
    def __init__(
        self,
        maker_fee_rate: Decimal = Decimal("0.0002"),
        taker_fee_rate: Decimal = Decimal("0.0006"),
    ) -> None:
        self._maker_fee_rate = maker_fee_rate
        self._taker_fee_rate = taker_fee_rate
        self._current_snapshot: MarketSnapshot | None = None
        self._fills: list[FillEvent] = []
        self._orders: dict[str, OrderState] = {}
        self._positions: dict[str, _PaperPosition] = {}

    def set_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        self._current_snapshot = snapshot

    def drain_fills(self) -> list[FillEvent]:
        fills = list(self._fills)
        self._fills.clear()
        return fills

    async def connect_public(self) -> None:
        return None

    async def connect_private(self) -> None:
        return None

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        return None

    async def subscribe_orderbook(self, symbols: list[str]) -> None:
        return None

    async def fetch_instruments(self) -> list[Instrument]:
        return []

    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, Decimal]:
        return {symbol: self._maker_fee_rate for symbol in symbols}

    async def fetch_market_snapshot(self, instrument: Instrument) -> MarketSnapshot | None:
        if self._current_snapshot and self._current_snapshot.instrument.symbol == instrument.symbol:
            return self._current_snapshot
        return None

    async def place_order(self, intent: OrderIntent) -> OrderAck:
        now = datetime.now(tz=UTC)
        exchange_order_id = f"paper-{len(self._orders) + 1}"
        self._orders[intent.client_order_id] = OrderState(
            client_order_id=intent.client_order_id,
            exchange_order_id=exchange_order_id,
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
        fill = self._fill_order(intent, exchange_order_id, now)
        self._fills.append(fill)
        self._orders[intent.client_order_id].status = OrderStatus.FILLED
        self._orders[intent.client_order_id].updated_at = fill.filled_at
        return OrderAck(
            client_order_id=intent.client_order_id,
            exchange_order_id=exchange_order_id,
            status=OrderStatus.ACCEPTED.value,
            accepted_at=now,
        )

    async def amend_order(self, req: AmendRequest) -> OrderAck:
        state = self._orders[req.client_order_id]
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
        state = self._orders[req.client_order_id]
        state.status = OrderStatus.CANCELED
        state.updated_at = datetime.now(tz=UTC)
        return CancelAck(
            client_order_id=req.client_order_id,
            status=OrderStatus.CANCELED.value,
            canceled_at=state.updated_at,
        )

    async def fetch_open_orders(self) -> list[OrderState]:
        return [order for order in self._orders.values() if order.status is OrderStatus.ACCEPTED]

    async def cancel_all(self) -> None:
        for order in self._orders.values():
            order.status = OrderStatus.CANCELED
            order.updated_at = datetime.now(tz=UTC)

    async def fetch_positions(self) -> list[PositionState]:
        if self._current_snapshot is None:
            mark_price = Decimal("0")
        else:
            mark_price = self._current_snapshot.perp_mid
        positions: list[PositionState] = []
        for position in self._positions.values():
            direction = Decimal("1") if position.side is SignalSide.LONG else Decimal("-1")
            unrealized = (mark_price - position.entry_price) * position.size * direction
            positions.append(
                PositionState(
                    exchange=ExchangeName.PAPER,
                    symbol=position.symbol,
                    side=position.side,
                    size=position.size,
                    entry_price=position.entry_price,
                    mark_price=mark_price,
                    unrealized_pnl=unrealized,
                    opened_at=position.opened_at,
                )
            )
        return positions

    def _fill_order(self, intent: OrderIntent, exchange_order_id: str, now: datetime) -> FillEvent:
        snapshot = self._current_snapshot
        if snapshot is None:
            raise RuntimeError("market snapshot must be set before placing paper order")
        if intent.order_type.value == "market":
            price = snapshot.perp_ask if intent.side is OrderSide.BUY else snapshot.perp_bid
            fee_rate = self._taker_fee_rate
            liquidity = "taker"
        else:
            price = intent.price
            fee_rate = self._maker_fee_rate if intent.post_only else self._taker_fee_rate
            liquidity = "maker" if intent.post_only else "taker"
        fee_paid = (price * intent.size * fee_rate).quantize(Decimal("0.00000001"))
        fill = FillEvent(
            client_order_id=intent.client_order_id,
            exchange_order_id=exchange_order_id,
            symbol=intent.symbol,
            side=intent.side,
            fill_price=price,
            fill_size=intent.size,
            fee_paid=fee_paid,
            liquidity=liquidity,
            filled_at=now,
            reduce_only=intent.reduce_only,
            meta=dict(intent.meta),
        )
        self._apply_fill(fill)
        return fill

    def _apply_fill(self, fill: FillEvent) -> None:
        current = self._positions.get(fill.symbol)
        fill_side = SignalSide.LONG if fill.side is OrderSide.BUY else SignalSide.SHORT
        if fill.reduce_only:
            if current is None:
                return
            remaining = current.size - fill.fill_size
            if remaining <= 0:
                self._positions.pop(fill.symbol, None)
                return
            current.size = remaining
            return
        if current is None:
            self._positions[fill.symbol] = _PaperPosition(
                symbol=fill.symbol,
                side=fill_side,
                size=fill.fill_size,
                entry_price=fill.fill_price,
                opened_at=fill.filled_at,
            )
            return
        total_size = current.size + fill.fill_size
        weighted_entry = ((current.entry_price * current.size) + (fill.fill_price * fill.fill_size)) / total_size
        current.size = total_size
        current.entry_price = weighted_entry
