from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from crypto_bot.core.config import StrategySettings, UniverseSettings
from crypto_bot.core.models import FeatureSnapshot, SignalCandidate, SignalSide
from crypto_bot.features.basis import listing_age_bonus


@dataclass(slots=True)
class BasisExtremeStrategy:
    settings: StrategySettings
    universe: UniverseSettings

    def evaluate(self, feature: FeatureSnapshot) -> SignalCandidate | None:
        if feature.listing_age_days < self.universe.min_listing_age_days:
            return None
        if feature.listing_age_days > self.universe.max_listing_age_days:
            return None
        if feature.spread_bps > self.universe.max_spread_bps:
            return None
        abs_basis_z = abs(feature.basis_z)
        if abs_basis_z < self.settings.entry_z_abs:
            return None
        side = SignalSide.LONG if feature.basis_z <= 0 else SignalSide.SHORT
        if self.settings.use_funding_filter:
            if side is SignalSide.LONG and feature.funding_rate > self.settings.funding_block_long_above:
                return None
            if side is SignalSide.SHORT and feature.funding_rate < self.settings.funding_block_short_below:
                return None
        score = (
            Decimal("0.35") * abs_basis_z
            + Decimal("0.20") * max(Decimal("0"), feature.volume_acceleration)
            + Decimal("0.15") * max(Decimal("0"), feature.oi_acceleration)
            + Decimal("0.10")
            * listing_age_bonus(
                feature.instrument,
                self.universe.min_listing_age_days,
                self.universe.max_listing_age_days,
            )
            + Decimal("0.10") * self._funding_alignment(side, feature.funding_rate)
            - Decimal("0.10") * (feature.spread_bps / max(Decimal("1"), self.universe.max_spread_bps))
        )
        mid = feature.perp_mid
        stop_offset = abs(feature.basis_z) * Decimal("0.003")
        target_offset = abs(feature.basis_z) * Decimal("0.002")
        if side is SignalSide.LONG:
            stop_price = mid * (Decimal("1") - stop_offset)
            target_price = mid * (Decimal("1") + target_offset)
        else:
            stop_price = mid * (Decimal("1") + stop_offset)
            target_price = mid * (Decimal("1") - target_offset)
        return SignalCandidate(
            instrument=feature.instrument,
            side=side,
            score=score,
            basis=feature.basis,
            basis_z=feature.basis_z,
            funding_rate=feature.funding_rate,
            spread_bps=feature.spread_bps,
            entry_price=mid,
            stop_price=stop_price,
            target_price=target_price,
            max_holding_time=timedelta(minutes=self.settings.max_hold_minutes),
            rationale=[
                f"basis_z={feature.basis_z}",
                f"funding={feature.funding_rate}",
                f"spread_bps={feature.spread_bps}",
            ],
            observed_at=feature.observed_at,
        )

    @staticmethod
    def _funding_alignment(side: SignalSide, funding_rate: Decimal) -> Decimal:
        if side is SignalSide.LONG:
            return max(Decimal("0"), Decimal("1") - max(Decimal("0"), funding_rate * Decimal("1000")))
        return max(Decimal("0"), Decimal("1") - max(Decimal("0"), abs(funding_rate) * Decimal("1000")))
