"""Historical portfolio performance endpoint. Reads stored data only."""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import NowDep, SessionDep, SettingsDep
from app.core.errors import AppError
from app.performance.benchmarks import available_benchmarks
from app.performance.allocation_service import build_allocation
from app.performance.intelligence import build_intelligence
from app.performance.ledger_views import build_attribution, build_pnl, build_timeline
from app.performance.schemas import (
    AllocationRead,
    AttributionRead,
    PortfolioIntelligenceRead,
    PortfolioPerformanceRead,
    PortfolioPnlRead,
    PortfolioTimelineRead,
)
from app.performance.service import build_performance
from app.schemas.system import ErrorResponse

router = APIRouter(tags=["performance"])

_ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorResponse} for code in (404, 422, 503)}


@router.get("/portfolios/{portfolio_id}/performance", response_model=PortfolioPerformanceRead, responses=_ERRORS)
def get_portfolio_performance(
    portfolio_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
    start_date: Annotated[date | None, Query(description="First session to include (inclusive).")] = None,
    end_date: Annotated[date | None, Query(description="Last session to include (inclusive).")] = None,
    benchmark: Annotated[str | None, Query(max_length=32, description="Benchmark key to compare against.")] = None,
) -> PortfolioPerformanceRead:
    """Daily portfolio value, returns and risk statistics from stored NSE end-of-day closes.

    Never calls the market-data provider and never interpolates: sessions without a complete
    set of closes are reported as missing.
    """
    if start_date and end_date and start_date > end_date:
        raise AppError(422, "invalid_date_range", "start_date must not be after end_date.")
    return build_performance(
        session, portfolio_id, settings=settings, now=now, start=start_date, end=end_date, benchmark=benchmark
    )


@router.get("/portfolios/{portfolio_id}/allocation", response_model=AllocationRead, responses=_ERRORS)
def get_portfolio_allocation(
    portfolio_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
) -> AllocationRead:
    """Position weights and concentration at the latest stored NSE closes.

    Unpriced holdings are listed separately rather than being weighted as zero, and sector
    allocation reports itself unavailable because no classification data exists.
    """
    return build_allocation(session, portfolio_id, settings=settings, now=now)


@router.get("/portfolios/{portfolio_id}/pnl", response_model=PortfolioPnlRead, responses=_ERRORS)
def get_portfolio_pnl(
    portfolio_id: uuid.UUID, session: SessionDep, settings: SettingsDep, now: NowDep
) -> PortfolioPnlRead:
    """Realised and unrealised profit on a FIFO cost basis, plus contributions and withdrawals.

    Needs a transaction ledger. Without one the response says so rather than returning zeros:
    holdings carry an average buy price but no disposals, so realised profit is unknowable.
    """
    return build_pnl(session, portfolio_id, settings=settings, now=now)


@router.get("/portfolios/{portfolio_id}/timeline", response_model=PortfolioTimelineRead, responses=_ERRORS)
def get_portfolio_timeline(
    portfolio_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
    limit: Annotated[int, Query(ge=1, le=500, description="Most recent entries to return.")] = 200,
) -> PortfolioTimelineRead:
    """Recorded transactions with the position change and portfolio value each one produced."""
    return build_timeline(session, portfolio_id, settings=settings, now=now, limit=limit)


@router.get("/portfolios/{portfolio_id}/attribution", response_model=AttributionRead, responses=_ERRORS)
def get_portfolio_attribution(
    portfolio_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
    start_date: Annotated[date | None, Query(description="First session to include (inclusive).")] = None,
    end_date: Annotated[date | None, Query(description="Last session to include (inclusive).")] = None,
    benchmark: Annotated[str | None, Query(max_length=32, description="Benchmark key to compare against.")] = None,
) -> AttributionRead:
    """Which securities moved the portfolio, over the window and on the latest session."""
    if start_date and end_date and start_date > end_date:
        raise AppError(422, "invalid_date_range", "start_date must not be after end_date.")
    return build_attribution(
        session, portfolio_id, settings=settings, now=now, start=start_date, end=end_date, benchmark=benchmark
    )


@router.get("/portfolios/{portfolio_id}/intelligence", response_model=PortfolioIntelligenceRead, responses=_ERRORS)
def get_portfolio_intelligence(
    portfolio_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    now: NowDep,
    start_date: Annotated[date | None, Query(description="First session to include (inclusive).")] = None,
    end_date: Annotated[date | None, Query(description="Last session to include (inclusive).")] = None,
    benchmark: Annotated[str | None, Query(max_length=32, description="Benchmark key to compare against.")] = None,
    top: Annotated[int, Query(ge=1, le=10, description="How many contributors to name on each side.")] = 3,
    trace: Annotated[bool, Query(description="Include the provenance of each headline figure.")] = False,
) -> PortfolioIntelligenceRead:
    """A deterministic explanation of the portfolio's measured numbers.

    Composes the performance, attribution, profit-and-loss and allocation calculations into
    structured facts and template sentences. It forecasts nothing, recommends nothing and
    generates no free-form text.
    """
    if start_date and end_date and start_date > end_date:
        raise AppError(422, "invalid_date_range", "start_date must not be after end_date.")
    return build_intelligence(
        session,
        portfolio_id,
        settings=settings,
        now=now,
        start=start_date,
        end=end_date,
        benchmark=benchmark,
        top=top,
        trace=trace,
    )


@router.get("/benchmarks", responses={503: {"model": ErrorResponse}})
def list_benchmarks() -> list[dict[str, object]]:
    """Benchmarks that can be requested for comparison.

    Listing one means the application knows how to price it, not that its history has been
    synced; a request for a benchmark with no stored closes returns ``no_data``.
    """
    return [
        {
            "key": item.key,
            "display_name": item.display_name,
            "symbol": item.nse_symbol,
            "exchange": item.exchange.value,
            "basis": item.basis,
            "tracks": item.tracks,
            "source": item.source,
            "is_proxy": item.is_proxy,
            "methodology": item.methodology,
            "note": item.note,
        }
        for item in available_benchmarks()
    ]
