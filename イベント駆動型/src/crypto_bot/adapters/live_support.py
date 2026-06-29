from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from crypto_bot.adapters.base import RateLimiter


@dataclass(slots=True)
class ApiCredentials:
    api_key: str
    api_secret: str
    passphrase: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def load_credentials(prefix: str, *, passphrase: bool = False) -> ApiCredentials:
    api_key = os.getenv(f"{prefix}_API_KEY", "")
    api_secret = os.getenv(f"{prefix}_API_SECRET", "")
    api_passphrase = os.getenv(f"{prefix}_API_PASSPHRASE", "") if passphrase else None
    return ApiCredentials(api_key=api_key, api_secret=api_secret, passphrase=api_passphrase)


def ensure_live_dependency() -> None:
    try:
        __import__("aiohttp")
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("Install aiohttp to use live WebSocket features.") from exc


def utc_ms() -> str:
    return str(int(datetime.now(UTC).timestamp() * 1000))


def utc_seconds() -> str:
    return str(int(datetime.now(UTC).timestamp()))


def hmac_sha256_hex(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_sha256_b64(secret: str, payload: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class RestClient:
    def __init__(self, *, base_url: str, timeout: float, rate_limiter: RateLimiter) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._rate_limiter = rate_limiter

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        await self._rate_limiter.wait_turn()
        query = query or {}
        body_text = "" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=True)
        query_string = urlencode({key: value for key, value in query.items() if value is not None})
        url = f"{self._base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        req = Request(url, method=method.upper())
        req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        data = None if not body_text else body_text.encode("utf-8")

        def _perform() -> dict[str, Any]:
            with urlopen(req, data=data, timeout=self._timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))

        return await asyncio.to_thread(_perform)


@dataclass(slots=True)
class WebSocketSubscription:
    payload: dict[str, Any]


@dataclass(slots=True)
class ManagedWebSocketConnection:
    url: str
    name: str
    ping_interval_seconds: int
    login_payload_factory: Callable[[], dict[str, Any] | None] | None = None
    on_message: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None
    message_buffer: list[dict[str, Any]] = field(default_factory=list)
    _subscriptions: list[WebSocketSubscription] = field(init=False, default_factory=list)
    _runner_task: asyncio.Task[None] | None = field(init=False, default=None)
    _closed: bool = field(init=False, default=False)
    _send_queue: asyncio.Queue[dict[str, Any]] = field(init=False)
    _connected_once: asyncio.Event = field(init=False)

    def __post_init__(self) -> None:
        self._send_queue = asyncio.Queue()
        self._connected_once = asyncio.Event()

    async def start(self) -> None:
        if self._runner_task is not None:
            return
        ensure_live_dependency()
        self._closed = False
        self._runner_task = asyncio.create_task(self._run_forever())
        await self._connected_once.wait()

    async def stop(self) -> None:
        self._closed = True
        if self._runner_task is not None:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
            self._runner_task = None

    async def subscribe(self, payload: dict[str, Any]) -> None:
        self._subscriptions.append(WebSocketSubscription(payload=payload))
        await self._send_queue.put(payload)

    async def send(self, payload: dict[str, Any]) -> None:
        await self._send_queue.put(payload)

    async def _run_forever(self) -> None:
        backoff = 1.0
        while not self._closed:
            try:
                await self._run_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _run_once(self) -> None:
        import aiohttp  # lazy import

        session_timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)
        async with aiohttp.ClientSession(timeout=session_timeout) as session:
            async with session.ws_connect(self.url, heartbeat=self.ping_interval_seconds) as ws:
                if self.login_payload_factory is not None:
                    login_payload = self.login_payload_factory()
                    if login_payload is not None:
                        await ws.send_json(login_payload)
                for subscription in self._subscriptions:
                    await ws.send_json(subscription.payload)
                self._connected_once.set()
                pinger = asyncio.create_task(self._ping_loop(ws))
                sender = asyncio.create_task(self._sender_loop(ws))
                try:
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(message.data)
                            if payload == "pong":
                                continue
                            self.message_buffer.append(payload)
                            if self.on_message is not None:
                                callback_result = self.on_message(payload)
                                if asyncio.iscoroutine(callback_result):
                                    await callback_result
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            raise RuntimeError(f"{self.name} websocket error")
                finally:
                    pinger.cancel()
                    sender.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pinger
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender

    async def _ping_loop(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self.ping_interval_seconds)
            await ws.send_str("ping")

    async def _sender_loop(self, ws: Any) -> None:
        while True:
            payload = await self._send_queue.get()
            await ws.send_json(payload)


def with_query(path: str, query: dict[str, Any]) -> str:
    encoded = urlencode({key: value for key, value in query.items() if value is not None})
    return path if not encoded else f"{path}?{encoded}"


def decode_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
