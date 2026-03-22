from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
import json
from time import monotonic
from urllib.error import URLError
from urllib.request import urlopen

from crypto_bot.core.models import Instrument, OrderAck, OrderIntent, PositionState


class ExchangeAdapter:
    async def connect_public(self) -> None: ...

    async def connect_private(self) -> None: ...

    async def subscribe_ticker(self, symbols: list[str]) -> None: ...

    async def subscribe_orderbook(self, symbols: list[str]) -> None: ...

    async def fetch_instruments(self) -> list[Instrument]: ...

    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, Decimal]: ...

    async def place_order(self, intent: OrderIntent) -> OrderAck: ...

    async def cancel_all(self) -> None: ...

    async def fetch_positions(self) -> list[PositionState]: ...


@dataclass(slots=True)
class RateLimiter:
    calls_per_second: int
    _last_call_at: float = 0.0

    async def wait_turn(self) -> None:
        if self.calls_per_second <= 0:
            return
        min_interval = 1 / self.calls_per_second
        elapsed = monotonic() - self._last_call_at
        if elapsed < min_interval:
            import asyncio

            await asyncio.sleep(min_interval - elapsed)
        self._last_call_at = monotonic()


async def with_retry(
    func: Callable[[], Awaitable[dict[str, object]]],
    retries: int = 3,
) -> dict[str, object]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return await func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt + 1 == retries:
                raise
            import asyncio

            await asyncio.sleep(0.25 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry loop exited unexpectedly")


async def fetch_json(url: str, timeout: float, rate_limiter: RateLimiter) -> dict[str, object]:
    await rate_limiter.wait_turn()

    def _request() -> dict[str, object]:
        try:
            with urlopen(url, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(f"request failed for {url}") from exc

    import asyncio

    return await asyncio.wait_for(asyncio.to_thread(_request), timeout=timeout + 0.5)
