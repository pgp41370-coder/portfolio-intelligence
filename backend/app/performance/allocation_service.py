"""Build the allocation response from the existing valuation.

Weights reuse ``app.valuation`` rather than re-pricing holdings, so allocation can never
disagree with the valuation card about what a position is worth.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.performance.allocation import PositionValue, concentration, weights
from app.performance.schemas import (
    AllocationRead,
    ConcentrationRead,
    SectorAllocationRead,
    UnpricedPositionRead,
    WeightRead,
)
from app.valuation.schemas import ValuationStatus
from app.valuation.service import value_portfolio

SECTOR_UNAVAILABLE_NOTE = (
    "Sector allocation is not available. The security master provides a name, an NSE symbol, a "
    "BSE code and an ISIN, but no sector or industry classification, and inferring one from a "
    "company's name would be guesswork. The field is reserved for a real classification source."
)


def build_allocation(
    session: Session, portfolio_id: uuid.UUID, *, settings: Settings, now: datetime
) -> AllocationRead:
    valuation = value_portfolio(session, portfolio_id, settings=settings, now=now)

    positions = [
        PositionValue(symbol=item.symbol, exchange=item.exchange.value, value=item.market_value)
        for item in valuation.holdings
        if item.market_value is not None and item.market_value > 0
    ]
    ranked = weights(positions)
    measured = concentration(ranked)

    unpriced = [
        UnpricedPositionRead(
            symbol=item.symbol,
            exchange=item.exchange,
            quantity=item.quantity,
            reason=item.unpriced_reason,
        )
        for item in valuation.holdings
        if item.status is ValuationStatus.UNPRICED or item.market_value is None
    ]

    return AllocationRead(
        portfolio_id=valuation.portfolio_id,
        portfolio_name=valuation.portfolio_name,
        as_of=now,
        data_as_of=valuation.freshness.latest_price_date,
        priced_market_value=sum((item.value for item in ranked), Decimal(0)) if ranked else None,
        holdings=[
            WeightRead(
                symbol=item.symbol,
                exchange=item.exchange,
                market_value=item.value,
                weight_pct=item.weight * Decimal(100),
            )
            for item in ranked
        ],
        concentration=ConcentrationRead(
            holdings_counted=measured.holdings_counted,
            top_holding=(
                WeightRead(
                    symbol=measured.top_weight.symbol,
                    exchange=measured.top_weight.exchange,
                    market_value=measured.top_weight.value,
                    weight_pct=measured.top_weight.weight * Decimal(100),
                )
                if measured.top_weight
                else None
            ),
            top_1_pct=measured.top_1_pct,
            top_3_pct=measured.top_3_pct,
            top_5_pct=measured.top_5_pct,
            hhi=measured.hhi,
            hhi_band=measured.hhi_band,
            effective_holdings=measured.effective_holdings,
        ),
        sectors=SectorAllocationRead(available=False, note=SECTOR_UNAVAILABLE_NOTE, weights=[]),
        unpriced_positions=unpriced,
        note=(
            "Weights are shares of the value of the priced holdings only. Unpriced holdings are "
            "listed separately and given no weight, because a position of unknown value cannot "
            "be sized."
        ),
    )
