from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from crypto_bot.adapters.base import ExchangeAdapter, RateLimiter
from crypto_bot.adapters.live_support import (
    ManagedWebSocketConnection,
    RestClient,
    hmac_sha256_hex,
    load_credentials,
    utc_ms,
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
class MexcContractSettings:
    rest_base_url: str = "https://contract.mexc.com"
    websocket_url: str = "wss://contract.mexc.com/edge"
    default_symbol: str = "BTC_USDT"
    recv_window_ms: int = 10000
    default_leverage: int = 3
    open_type: int = 1


class MexcPublicAdapter(ExchangeAdapter):
    def __init__(self, timeout: float = 5.0, settings: MexcContractSettings | None = None) -> None:
        self._settings = settings or MexcContractSettings()
        self._credentials = load_credentials("MEXC")
        self._http = RestClient(
            base_url=self._settings.rest_base_url,
            timeout=timeout,
            rate_limiter=RateLimiter(calls_per_second=8),
        )
        self._public_ws = ManagedWebSocketConnection(
            url=self._settings.websocket_url,
            name="mexc-public",
            ping_interval_seconds=15,
        )
        self._private_ws = ManagedWebSocketConnection(
            url=self._settings.websocket_url,
            name="mexc-private",
            ping_interval_seconds=15,
            login_payload_factory=self._private_login_payload,
        )

    async def connect_public(self) -> None:
        await self._public_ws.start()

    async def connect_private(self) -> None:
        self._require_credentials()
        await self._private_ws.start()
        await self._private_ws.send({"method": "personal.filter", "param": {"filters": []}})

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        await self.connect_public()
        for symbol in symbols:
            await self._public_ws.subscribe(
                {"method": "sub.ticker", "param": {"symbol": self._to_exchange_symbol(symbol)}}
            )

    async def subscribe_orderbook(self, symbols: list[str]) -> None:
        await self.connect_public()
        for symbol in symbols:
            await self._public_ws.subscribe(
                {"method": "sub.depth.full", "param": {"symbol": self._to_exchange_symbol(symbol), "limit": 20}}
            )

    async def subscribe_private_defaults(self) -> None:
        await self.connect_private()
        await self._private_ws.send(
            {
                "method": "personal.filter",
                "param": {
                    "filters": [
                        {"filter": "order"},
                        {"filter": "order.deal"},
                        {"filter": "position"},
                        {"filter": "asset"},
                    ]
                },
            }
        )

    async def fetch_instruments(self) -> list[Instrument]:
        payload = await self._http.request_json("GET", "/api/v1/contract/detail")
        instruments: list[Instrument] = []
        for item in payload.get("data", []):
            symbol = str(item.get("symbol", ""))
            if not symbol:
                continue
            instruments.append(
                Instrument(
                    exchange=ExchangeName.MEXC,
                    symbol=normalize_symbol(symbol),
                    base=str(item.get("baseCoin", symbol.split("_")[0])),
                    quote=str(item.get("quoteCoin", symbol.split("_")[-1])),
                    spot_symbol=normalize_symbol(symbol),
                    perp_symbol=symbol,
                    listing_time=datetime.fromtimestamp(0, tz=UTC),
                    tick_size=Decimal(str(item.get("priceUnit", "0.0001"))),
                    lot_size=Decimal(str(item.get("volUnit", "0.001"))),
                    min_notional=Decimal("5"),
                )
            )
        return instruments

    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, Decimal]:
        self._require_credentials()
        payload = await self._private_request("GET", "/api/v1/private/account/tiered_fee_rate")
        rates: dict[str, Decimal] = {}
        for row in payload.get("data", []):
            rates[normalize_symbol(str(row.get("symbol", "")))] = Decimal(str(row.get("makerFee", "0.0002")))
        for symbol in symbols:
            rates.setdefault(normalize_symbol(symbol), Decimal("0.0002"))
        return rates

    async def fetch_market_snapshot(self, instrument: Instrument) -> MarketSnapshot | None:
        payload = await self._http.request_json(
            "GET",
            "/api/v1/contract/ticker",
            query={"symbol": instrument.perp_symbol},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        bid = Decimal(str(data.get("bid1", data.get("lastPrice", "0"))))
        ask = Decimal(str(data.get("ask1", data.get("lastPrice", "0"))))
        observed = datetime.fromtimestamp(int(data.get("timestamp", utc_ms())) / 1000, tz=UTC)
        return MarketSnapshot(
            instrument=instrument,
            spot_bid=bid,
            spot_ask=ask,
            perp_bid=bid,
            perp_ask=ask,
            funding_rate=Decimal(str(data.get("fundingRate", "0"))),
            volume_24h_usd=Decimal(str(data.get("amount24", "0"))),
            open_interest_usd=Decimal(str(data.get("holdVol", "0"))),
            depth_usd_at_5bps=Decimal("0"),
            observed_at=observed,
        )

    async def place_order(self, intent: OrderIntent) -> OrderAck:
        self._require_credentials()
        payload = {
            "symbol": intent.symbol,
            "price": str(intent.price),
            "vol": str(intent.size),
            "leverage": self._settings.default_leverage,
            "side": self._intent_side(intent),
            "type": 2 if intent.post_only else 1,
            "openType": self._settings.open_type,
            "externalOid": intent.client_order_id,
        }
        result = await self._private_request("POST", "/api/v1/private/order/submit", body=payload)
        return OrderAck(
            client_order_id=intent.client_order_id,
            exchange_order_id=str(result.get("data", intent.client_order_id)),
            status=OrderStatus.ACCEPTED.value,
            accepted_at=datetime.now(tz=UTC),
        )

    async def amend_order(self, req: AmendRequest) -> OrderAck:
        current = await self._lookup_order(req.client_order_id)
        payload = {
            "symbol": current["symbol"],
            "price": str(req.new_price if req.new_price is not None else current["price"]),
            "vol": str(req.new_size if req.new_size is not None else current["vol"]),
            "leverage": int(current.get("leverage", self._settings.default_leverage)),
            "side": int(current["side"]),
            "type": int(current.get("orderType", 1)),
            "openType": int(current.get("openType", self._settings.open_type)),
            "externalOid": f"{req.client_order_id}-amend",
        }
        result = await self._private_request("POST", "/api/v1/private/order/submit", body=payload)
        return OrderAck(
            client_order_id=req.client_order_id,
            exchange_order_id=str(result.get("data", req.client_order_id)),
            status=OrderStatus.ACCEPTED.value,
            accepted_at=datetime.now(tz=UTC),
        )

    async def cancel_order(self, req: CancelRequest) -> CancelAck:
        self._require_credentials()
        await self._private_request(
            "POST",
            "/api/v1/private/order/cancel_with_external",
            body={"symbol": self._settings.default_symbol, "externalOid": req.client_order_id},
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
            f"/api/v1/private/order/list/open_orders/{self._settings.default_symbol}",
            query={"page_num": 1, "page_size": 100},
        )
        return [self._to_order_state(row) for row in payload.get("data", [])]

    async def cancel_all(self) -> None:
        self._require_credentials()
        await self._private_request(
            "POST",
            "/api/v1/private/order/cancel_all",
            body={"symbol": self._settings.default_symbol},
        )

    async def fetch_positions(self) -> list[PositionState]:
        self._require_credentials()
        payload = await self._private_request(
            "GET",
            "/api/v1/private/position/open_positions",
            query={"symbol": self._settings.default_symbol},
        )
        positions: list[PositionState] = []
        for row in payload.get("data", []):
            side = SignalSide.LONG if int(row.get("positionType", 1)) == 1 else SignalSide.SHORT
            entry_price = Decimal(str(row.get("openAvgPrice", row.get("holdAvgPrice", "0"))))
            mark_price = Decimal(str(row.get("holdAvgPrice", entry_price)))
            size = Decimal(str(row.get("holdVol", "0")))
            direction = Decimal("1") if side is SignalSide.LONG else Decimal("-1")
            positions.append(
                PositionState(
                    exchange=ExchangeName.MEXC,
                    symbol=str(row.get("symbol", "")),
                    side=side,
                    size=size,
                    entry_price=entry_price,
                    mark_price=mark_price,
                    unrealized_pnl=(mark_price - entry_price) * size * direction,
                    opened_at=datetime.fromtimestamp(int(row.get("createTime", utc_ms())) / 1000, tz=UTC),
                )
            )
        return positions

    async def close(self) -> None:
        await self._public_ws.stop()
        await self._private_ws.stop()

    def _private_login_payload(self) -> dict[str, Any] | None:
        self._require_credentials()
        req_time = utc_ms()
        signature = hmac_sha256_hex(self._credentials.api_secret, f"{self._credentials.api_key}{req_time}")
        return {
            "method": "login",
            "param": {
                "apiKey": self._credentials.api_key,
                "reqTime": req_time,
                "signature": signature,
            },
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
        timestamp = utc_ms()
        params = query if method.upper() in {"GET", "DELETE"} else body
        signature = hmac_sha256_hex(
            self._credentials.api_secret,
            f"{self._credentials.api_key}{timestamp}{self._param_text(params)}",
        )
        headers = {
            "ApiKey": self._credentials.api_key,
            "Request-Time": timestamp,
            "Signature": signature,
            "Recv-Window": str(self._settings.recv_window_ms),
        }
        return await self._http.request_json(method, path, query=query, body=body, headers=headers)

    async def _lookup_order(self, client_order_id: str) -> dict[str, Any]:
        payload = await self._private_request(
            "GET",
            f"/api/v1/private/order/external/{self._settings.default_symbol}/{client_order_id}",
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(f"MEXC order not found for externalOid={client_order_id}")
        return data

    def _require_credentials(self) -> None:
        if not self._credentials.is_configured:
            raise RuntimeError("Set MEXC_API_KEY and MEXC_API_SECRET before using live MEXC features.")

    @staticmethod
    def _param_text(payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""
        return "&".join(f"{key}={payload[key]}" for key in sorted(payload) if payload[key] is not None)

    @staticmethod
    def _intent_side(intent: OrderIntent) -> int:
        if intent.reduce_only and intent.side is OrderSide.BUY:
            return 2
        if intent.reduce_only and intent.side is OrderSide.SELL:
            return 4
        if intent.side is OrderSide.BUY:
            return 1
        return 3

    @staticmethod
    def _to_order_state(row: dict[str, Any]) -> OrderState:
        mapping = {1: OrderStatus.NEW, 2: OrderStatus.ACCEPTED, 3: OrderStatus.FILLED, 4: OrderStatus.CANCELED, 5: OrderStatus.REJECTED}
        return OrderState(
            client_order_id=str(row.get("externalOid", row.get("orderId", ""))),
            exchange_order_id=str(row.get("orderId", "")),
            symbol=str(row.get("symbol", "")),
            side=OrderSide.BUY if int(row.get("side", 1)) in {1, 2} else OrderSide.SELL,
            price=Decimal(str(row.get("price", "0"))),
            size=Decimal(str(row.get("vol", "0"))),
            status=mapping.get(int(row.get("state", 1)), OrderStatus.NEW),
            reduce_only=int(row.get("side", 1)) in {2, 4},
            post_only=int(row.get("orderType", 1)) == 2,
            created_at=datetime.fromtimestamp(int(row.get("createTime", utc_ms())) / 1000, tz=UTC),
            updated_at=datetime.fromtimestamp(int(row.get("updateTime", utc_ms())) / 1000, tz=UTC),
        )

    @staticmethod
    def _to_exchange_symbol(symbol: str) -> str:
        normalized = normalize_symbol(symbol)
        if "_" in symbol:
            return symbol.upper()
        if normalized.endswith("USDT"):
            return f"{normalized[:-4]}_USDT"
        return normalized

    @staticmethod
    def normalize_symbol(raw_symbol: str) -> str:
        return normalize_symbol(raw_symbol)
