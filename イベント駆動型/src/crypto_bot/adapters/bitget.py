from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from crypto_bot.adapters.base import ExchangeAdapter, RateLimiter
from crypto_bot.adapters.live_support import (
    ManagedWebSocketConnection,
    RestClient,
    hmac_sha256_b64,
    load_credentials,
    utc_ms,
    utc_seconds,
)
from crypto_bot.collectors.normalizer import normalize_symbol
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
    SignalSide,
    UTC,
)


@dataclass(slots=True)
class BitgetContractSettings:
    rest_base_url: str = "https://api.bitget.com"
    public_ws_url: str = "wss://ws.bitget.com/v2/ws/public"
    private_ws_url: str = "wss://ws.bitget.com/v2/ws/private"
    product_type: str = "USDT-FUTURES"
    margin_coin: str = "USDT"
    margin_mode: str = "crossed"
    default_symbol: str = "BTCUSDT"


class BitgetPublicAdapter(ExchangeAdapter):
    def __init__(self, timeout: float = 5.0, settings: BitgetContractSettings | None = None) -> None:
        self._settings = settings or BitgetContractSettings()
        self._credentials = load_credentials("BITGET", passphrase=True)
        self._http = RestClient(
            base_url=self._settings.rest_base_url,
            timeout=timeout,
            rate_limiter=RateLimiter(calls_per_second=8),
        )
        self._public_ws = ManagedWebSocketConnection(
            url=self._settings.public_ws_url,
            name="bitget-public",
            ping_interval_seconds=25,
        )
        self._private_ws = ManagedWebSocketConnection(
            url=self._settings.private_ws_url,
            name="bitget-private",
            ping_interval_seconds=25,
            login_payload_factory=self._private_login_payload,
        )

    async def connect_public(self) -> None:
        await self._public_ws.start()

    async def connect_private(self) -> None:
        self._require_credentials()
        await self._private_ws.start()

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        await self.connect_public()
        for symbol in symbols:
            await self._public_ws.subscribe(
                {
                    "op": "subscribe",
                    "args": [
                        {
                            "instType": self._settings.product_type,
                            "channel": "ticker",
                            "instId": normalize_symbol(symbol),
                        }
                    ],
                }
            )

    async def subscribe_orderbook(self, symbols: list[str]) -> None:
        await self.connect_public()
        for symbol in symbols:
            await self._public_ws.subscribe(
                {
                    "op": "subscribe",
                    "args": [
                        {
                            "instType": self._settings.product_type,
                            "channel": "books1",
                            "instId": normalize_symbol(symbol),
                        }
                    ],
                }
            )

    async def subscribe_private_defaults(self) -> None:
        await self.connect_private()
        for arg in (
            {"instType": self._settings.product_type, "channel": "positions", "instId": "default"},
            {"instType": self._settings.product_type, "channel": "orders", "instId": "default"},
            {"instType": self._settings.product_type, "channel": "fill", "instId": "default"},
            {"instType": self._settings.product_type, "channel": "account", "coin": "default"},
        ):
            await self._private_ws.subscribe({"op": "subscribe", "args": [arg]})

    async def fetch_instruments(self) -> list[Instrument]:
        payload = await self._http.request_json(
            "GET",
            "/api/v2/mix/market/contracts",
            query={"productType": self._settings.product_type},
        )
        instruments: list[Instrument] = []
        for item in payload.get("data", []):
            symbol = str(item.get("symbol", "")).upper()
            if not symbol:
                continue
            instruments.append(
                Instrument(
                    exchange=ExchangeName.BITGET,
                    symbol=normalize_symbol(symbol),
                    base=str(item.get("baseCoin", symbol[:-4])),
                    quote=str(item.get("quoteCoin", symbol[-4:])),
                    spot_symbol=normalize_symbol(symbol),
                    perp_symbol=normalize_symbol(symbol),
                    listing_time=datetime.fromtimestamp(0, tz=UTC),
                    tick_size=Decimal(str(item.get("priceEndStep", "0.1"))),
                    lot_size=Decimal(str(item.get("sizeMultiplier", "0.001"))),
                    min_notional=Decimal(str(item.get("minTradeUSDT", "5"))),
                )
            )
        return instruments

    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, Decimal]:
        self._require_credentials()
        return {normalize_symbol(symbol): Decimal("0.0002") for symbol in symbols}

    async def fetch_market_snapshot(self, instrument: Instrument) -> MarketSnapshot | None:
        payload = await self._http.request_json(
            "GET",
            "/api/v2/mix/market/ticker",
            query={"symbol": instrument.perp_symbol, "productType": self._settings.product_type.lower()},
        )
        rows = payload.get("data", [])
        data = rows[0] if isinstance(rows, list) and rows else payload.get("data")
        if not isinstance(data, dict):
            return None
        bid = Decimal(str(data.get("bidPr", data.get("lastPr", "0"))))
        ask = Decimal(str(data.get("askPr", data.get("lastPr", "0"))))
        observed = datetime.fromtimestamp(int(data.get("ts", utc_ms())) / 1000, tz=UTC)
        return MarketSnapshot(
            instrument=instrument,
            spot_bid=bid,
            spot_ask=ask,
            perp_bid=bid,
            perp_ask=ask,
            funding_rate=Decimal(str(data.get("fundingRate", "0"))),
            volume_24h_usd=Decimal(str(data.get("usdtVolume", "0"))),
            open_interest_usd=Decimal(str(data.get("holdingAmount", "0"))),
            depth_usd_at_5bps=Decimal("0"),
            observed_at=observed,
        )

    async def place_order(self, intent: OrderIntent) -> OrderAck:
        self._require_credentials()
        body = {
            "symbol": normalize_symbol(intent.symbol),
            "productType": self._settings.product_type.lower(),
            "marginCoin": self._settings.margin_coin,
            "marginMode": self._settings.margin_mode,
            "side": intent.side.value,
            "orderType": intent.order_type.value,
            "force": intent.time_in_force.value,
            "size": str(intent.size),
            "clientOid": intent.client_order_id,
            "reduceOnly": "YES" if intent.reduce_only else "NO",
        }
        if intent.order_type.value == "limit":
            body["price"] = str(intent.price)
        result = await self._private_request("POST", "/api/v2/mix/order/place-order", body=body)
        data = result.get("data", {})
        return OrderAck(
            client_order_id=intent.client_order_id,
            exchange_order_id=str(data.get("orderId", intent.client_order_id)),
            status=OrderStatus.ACCEPTED.value,
            accepted_at=datetime.now(tz=UTC),
        )

    async def amend_order(self, req: AmendRequest) -> OrderAck:
        current = await self._lookup_order(req.client_order_id)
        body = {
            "clientOid": req.client_order_id,
            "newClientOid": f"{req.client_order_id}-amend",
            "symbol": str(current.get("symbol", self._settings.default_symbol)).upper(),
            "productType": self._settings.product_type.lower(),
            "marginCoin": self._settings.margin_coin,
            "newSize": str(req.new_size if req.new_size is not None else current.get("size", "0")),
            "newPrice": str(req.new_price if req.new_price is not None else current.get("price", "0")),
        }
        result = await self._private_request("POST", "/api/v2/mix/order/modify-order", body=body)
        data = result.get("data", {})
        return OrderAck(
            client_order_id=req.client_order_id,
            exchange_order_id=str(data.get("orderId", req.client_order_id)),
            status=OrderStatus.ACCEPTED.value,
            accepted_at=datetime.now(tz=UTC),
        )

    async def cancel_order(self, req: CancelRequest) -> CancelAck:
        self._require_credentials()
        await self._private_request(
            "POST",
            "/api/v2/mix/order/cancel-order",
            body={
                "clientOid": req.client_order_id,
                "symbol": self._settings.default_symbol,
                "productType": self._settings.product_type.lower(),
                "marginCoin": self._settings.margin_coin,
            },
        )
        return CancelAck(
            client_order_id=req.client_order_id,
            status=OrderStatus.CANCELED.value,
            canceled_at=datetime.now(tz=UTC),
        )

    async def fetch_open_orders(self) -> list[OrderState]:
        self._require_credentials()
        payload = await self._private_request(
            "GET",
            "/api/v2/mix/order/orders-pending",
            query={"productType": self._settings.product_type.lower(), "limit": 100},
        )
        data = payload.get("data", {})
        rows = data.get("entrustedList", data if isinstance(data, list) else [])
        return [self._to_order_state(row) for row in rows]

    async def cancel_all(self) -> None:
        for order in await self.fetch_open_orders():
            await self.cancel_order(CancelRequest(client_order_id=order.client_order_id))

    async def fetch_positions(self) -> list[PositionState]:
        self._require_credentials()
        payload = await self._private_request(
            "GET",
            "/api/v2/mix/position/all-position",
            query={"productType": self._settings.product_type, "marginCoin": self._settings.margin_coin},
        )
        positions: list[PositionState] = []
        for row in payload.get("data", []):
            size = Decimal(str(row.get("total", "0")))
            if size == 0:
                continue
            side = SignalSide.LONG if str(row.get("holdSide", "long")).lower() == "long" else SignalSide.SHORT
            entry_price = Decimal(str(row.get("openPriceAvg", row.get("avgOpenPrice", "0"))))
            mark_price = Decimal(str(row.get("markPrice", entry_price)))
            direction = Decimal("1") if side is SignalSide.LONG else Decimal("-1")
            positions.append(
                PositionState(
                    exchange=ExchangeName.BITGET,
                    symbol=str(row.get("symbol", "")),
                    side=side,
                    size=size,
                    entry_price=entry_price,
                    mark_price=mark_price,
                    unrealized_pnl=(mark_price - entry_price) * size * direction,
                    opened_at=datetime.fromtimestamp(int(row.get("cTime", utc_ms())) / 1000, tz=UTC),
                )
            )
        return positions

    async def close(self) -> None:
        await self._public_ws.stop()
        await self._private_ws.stop()

    def _private_login_payload(self) -> dict[str, Any] | None:
        self._require_credentials()
        timestamp = utc_seconds()
        sign = hmac_sha256_b64(self._credentials.api_secret, f"{timestamp}GET/user/verify")
        return {
            "op": "login",
            "args": [
                {
                    "apiKey": self._credentials.api_key,
                    "passphrase": self._credentials.passphrase,
                    "timestamp": timestamp,
                    "sign": sign,
                }
            ],
        }

    async def _private_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_credentials()
        query = query or {}
        timestamp = utc_ms()
        body_text = self._json_text(body) if body else ""
        query_text = self._query_text(query)
        sign_payload = f"{timestamp}{method.upper()}{path}"
        if query_text:
            sign_payload = f"{sign_payload}?{query_text}"
        sign_payload = f"{sign_payload}{body_text}"
        headers = {
            "ACCESS-KEY": self._credentials.api_key,
            "ACCESS-SIGN": hmac_sha256_b64(self._credentials.api_secret, sign_payload),
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self._credentials.passphrase or "",
            "locale": "en-US",
        }
        return await self._http.request_json(method, path, query=query, body=body, headers=headers)

    async def _lookup_order(self, client_order_id: str) -> dict[str, Any]:
        payload = await self._private_request(
            "GET",
            "/api/v2/mix/order/orders-pending",
            query={"productType": self._settings.product_type.lower(), "clientOid": client_order_id, "limit": 1},
        )
        data = payload.get("data", {})
        rows = data.get("entrustedList", [])
        if not rows:
            raise RuntimeError(f"Bitget order not found for clientOid={client_order_id}")
        return rows[0]

    def _require_credentials(self) -> None:
        if not self._credentials.is_configured or not self._credentials.passphrase:
            raise RuntimeError(
                "Set BITGET_API_KEY, BITGET_API_SECRET, and BITGET_API_PASSPHRASE before using live Bitget features."
            )

    @staticmethod
    def _json_text(body: dict[str, Any]) -> str:
        import json

        return json.dumps(body, separators=(",", ":"), ensure_ascii=True)

    @staticmethod
    def _query_text(query: dict[str, Any]) -> str:
        from urllib.parse import urlencode

        return urlencode({key: value for key, value in query.items() if value is not None})

    @staticmethod
    def _to_order_state(row: dict[str, Any]) -> OrderState:
        status = str(row.get("state", row.get("status", "live"))).lower()
        mapped = {
            "new": OrderStatus.NEW,
            "live": OrderStatus.ACCEPTED,
            "partially_filled": OrderStatus.ACCEPTED,
            "filled": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELED,
            "canceled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
        }.get(status, OrderStatus.ACCEPTED)
        return OrderState(
            client_order_id=str(row.get("clientOid", "")),
            exchange_order_id=str(row.get("orderId", "")),
            symbol=str(row.get("symbol", "")).upper(),
            side=OrderSide.BUY if str(row.get("side", "buy")).lower() == "buy" else OrderSide.SELL,
            price=Decimal(str(row.get("price", "0"))),
            size=Decimal(str(row.get("size", row.get("baseVolume", "0")))),
            status=mapped,
            reduce_only=str(row.get("reduceOnly", "no")).lower() in {"yes", "true"},
            post_only=str(row.get("orderType", "limit")).lower() == "post_only",
            created_at=datetime.fromtimestamp(int(row.get("cTime", utc_ms())) / 1000, tz=UTC),
            updated_at=datetime.fromtimestamp(int(row.get("uTime", utc_ms())) / 1000, tz=UTC),
        )

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        return normalize_symbol(raw_symbol)
