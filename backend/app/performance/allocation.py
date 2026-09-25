"""Allocation and concentration analytics.

Weights come from the same valuation the rest of the application uses: quantity x the latest
stored NSE end-of-day close. Unpriced holdings are never given a weight - an unpriced position
is of unknown size, and treating it as zero would understate concentration in exactly the
situation where concentration matters most.

**Sector data does not exist.** The security master carries a name, an NSE symbol, a BSE code
and an ISIN - no sector or industry classification. Sector weights are therefore reported as
unavailable, with the shape of the answer already defined so that a future classification
source slots in without changing the API. Guessing a sector from a company's name would be
fabrication of exactly the kind this project refuses elsewhere.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)
_HUNDRED = Decimal(100)

# Concentration bands for the Herfindahl-Hirschman Index, expressed on the 0-10,000 scale the
# US DOJ/FTC merger guidelines use for market concentration. The thresholds are theirs; the
# reading is descriptive, not advice.
HHI_UNCONCENTRATED = Decimal(1500)
HHI_MODERATE = Decimal(2500)


@dataclass(frozen=True, slots=True)
class PositionValue:
    symbol: str
    exchange: str
    value: Decimal


@dataclass(frozen=True, slots=True)
class Weight:
    symbol: str
    exchange: str
    value: Decimal
    weight: Decimal  # fraction of the priced total, 0-1


@dataclass(frozen=True, slots=True)
class Concentration:
    holdings_counted: int
    top_weight: Weight | None
    top_1_pct: Decimal | None
    top_3_pct: Decimal | None
    top_5_pct: Decimal | None
    hhi: Decimal | None
    hhi_band: str | None
    effective_holdings: Decimal | None  # 1 / sum(w^2): how many equal positions this resembles


def weights(positions: Sequence[PositionValue]) -> list[Weight]:
    """Weight of each priced position, largest first. Positions worth nothing are dropped."""
    priced = [item for item in positions if item.value > 0]
    total = sum((item.value for item in priced), Decimal(0))
    if total <= 0:
        return []
    with localcontext(_CONTEXT):
        computed = [
            Weight(item.symbol, item.exchange, item.value, item.value / total) for item in priced
        ]
    return sorted(computed, key=lambda item: (-item.weight, item.symbol))


def concentration(ranked: Sequence[Weight]) -> Concentration:
    """Top-N shares and the Herfindahl-Hirschman Index over the priced positions."""
    if not ranked:
        return Concentration(0, None, None, None, None, None, None, None)
    with localcontext(_CONTEXT):
        cumulative = lambda count: sum((item.weight for item in ranked[:count]), Decimal(0)) * _HUNDRED  # noqa: E731
        hhi = sum(((item.weight * _HUNDRED) ** 2 for item in ranked), Decimal(0))
        sum_of_squares = sum((item.weight**2 for item in ranked), Decimal(0))
        effective = (Decimal(1) / sum_of_squares) if sum_of_squares > 0 else None
        return Concentration(
            holdings_counted=len(ranked),
            top_weight=ranked[0],
            top_1_pct=cumulative(1),
            # Top-3 and top-5 of fewer holdings than that is just the whole portfolio, which is
            # true and worth saying rather than withholding.
            top_3_pct=cumulative(3),
            top_5_pct=cumulative(5),
            hhi=hhi,
            hhi_band=hhi_band(hhi),
            effective_holdings=effective,
        )


def hhi_band(hhi: Decimal | None) -> str | None:
    """A plain description of the index, using the standard 0-10,000 thresholds."""
    if hhi is None:
        return None
    if hhi < HHI_UNCONCENTRATED:
        return "diversified"
    if hhi < HHI_MODERATE:
        return "moderately concentrated"
    return "highly concentrated"
