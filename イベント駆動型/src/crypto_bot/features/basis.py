from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

from crypto_bot.core.models import FeatureSnapshot, Instrument, MarketSnapshot


@dataclass(slots=True)
class RollingSeries:
    basis: deque[Decimal]
    volume: deque[Decimal]
    open_interest: deque[Decimal]


class FeatureEngine:
    def __init__(self, basis_window: int) -> None:
        self._basis_window = basis_window
        self._state: dict[str, RollingSeries] = defaultdict(
            lambda: RollingSeries(deque(maxlen=basis_window), deque(maxlen=60), deque(maxlen=60))
        )

    def update(self, snapshot: MarketSnapshot) -> FeatureSnapshot | None:
        if snapshot.spot_mid == 0 or snapshot.perp_mid == 0:
            return None
        basis = (snapshot.perp_mid / snapshot.spot_mid) - Decimal("1")
        series = self._state[snapshot.instrument.symbol]
        series.basis.append(basis)
        series.volume.append(snapshot.volume_24h_usd)
        series.open_interest.append(snapshot.open_interest_usd)
        if len(series.basis) < 2:
            return None
        basis_z = self._zscore(series.basis, basis)
        return FeatureSnapshot(
            instrument=snapshot.instrument,
            spot_mid=snapshot.spot_mid,
            perp_mid=snapshot.perp_mid,
            basis=basis,
            basis_z=basis_z,
            funding_rate=snapshot.funding_rate,
            volume_acceleration=self._acceleration(series.volume),
            oi_acceleration=self._acceleration(series.open_interest),
            listing_age_days=snapshot.instrument.listing_age_days,
            spread_bps=snapshot.spread_bps,
            depth_usd_at_5bps=snapshot.depth_usd_at_5bps,
            observed_at=snapshot.observed_at,
        )

    @staticmethod
    def _zscore(values: deque[Decimal], latest: Decimal) -> Decimal:
        mean = sum(values) / Decimal(len(values))
        variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
        std = Decimal(str(sqrt(float(variance)))) if variance > 0 else Decimal("0")
        if std == 0:
            return Decimal("0")
        return (latest - mean) / std

    @staticmethod
    def _acceleration(values: deque[Decimal]) -> Decimal:
        if len(values) < 2 or values[0] == 0:
            return Decimal("0")
        baseline = sum(values) / Decimal(len(values))
        if baseline == 0:
            return Decimal("0")
        return (values[-1] / baseline) - Decimal("1")


def listing_age_bonus(instrument: Instrument, minimum_days: int, maximum_days: int) -> Decimal:
    age = instrument.listing_age_days
    if age < minimum_days or age > maximum_days:
        return Decimal("0")
    midpoint = (minimum_days + maximum_days) / 2
    distance = abs(age - midpoint) / midpoint if midpoint else 0
    return Decimal(str(max(0.0, 1.0 - distance)))
