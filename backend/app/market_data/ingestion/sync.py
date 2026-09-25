"""Market-data synchronisation.

Nothing here runs during a web request. Syncs are started from the CLI (or a scheduler),
hold a PostgreSQL advisory lock so two syncs cannot overlap, and record every run in
``market_data_sync_runs``. Price syncs only request held NSE securities that do not yet
have the latest expected session, and stop immediately on authentication failures,
HTTP 429, provider outages or an exhausted monthly request budget.
"""

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.market_data import repository
from app.market_data.budget import RequestBudget
from app.market_data.calendar import (
    TradingCalendar,
    eod_available_at,
    is_completed_session_close,
    ist_month_start,
    latest_expected_session,
    now_utc,
)
from app.market_data.exceptions import (
    MarketDataError,
    ProviderAuthenticationError,
    ProviderGranularityError,
    ProviderNotConfiguredError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderUnavailableError,
    RequestBudgetExceededError,
    SyncAlreadyRunningError,
)
from app.market_data.models import Listing, MarketDataSyncRun
from app.market_data.providers.base import MarketDataProvider
from app.market_data.records import DailyPriceSeries, HistoricalPeriod
from app.performance.benchmarks import available_benchmarks
from app.portfolios.rules import Exchange

logger = logging.getLogger(__name__)

KIND_SECURITY_MASTER = "security_master"
KIND_DAILY_PRICES = "daily_prices"
SYNC_LOCK_ID = 7_310_442_001
BACKFILL_GAP_DAYS = 28
LARGE_MOVE_THRESHOLD = Decimal("0.35")
MIN_MASTER_RETENTION = Decimal("0.5")
MAX_ERRORS_RECORDED = 25
# Several rejected or invalid responses in a row usually mean every request will fail (for example
# an error body returned with HTTP 200), so the sync stops instead of spending the monthly budget.
MAX_CONSECUTIVE_REJECTIONS = 3
MAX_ERROR_SUMMARY_LENGTH = 1000

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PlannedRequest:
    listing_id: uuid.UUID
    nse_symbol: str
    period: HistoricalPeriod
    latest_stored_date: date | None


@dataclass
class PriceSyncPlan:
    expected_session: date
    requests: list[PlannedRequest]
    up_to_date: list[str]
    already_requested_this_session: list[str]
    unmatched_nse_symbols: list[str]
    unmatched_bse_codes: list[str]
    bse_without_nse_listing: list[str]
    # A registered benchmark missing from the security master is reported here, not as an
    # unmatched holding: nobody holds it, the application prices it for comparison.
    unmatched_benchmark_symbols: list[str] = field(default_factory=list)

    def as_details(self) -> dict[str, Any]:
        return {
            "expected_session": self.expected_session.isoformat(),
            "planned": [{"symbol": item.nse_symbol, "period": item.period} for item in self.requests],
            "up_to_date": self.up_to_date,
            "already_requested_this_session": self.already_requested_this_session,
            "unmatched_nse_symbols": self.unmatched_nse_symbols,
            "unmatched_benchmark_symbols": self.unmatched_benchmark_symbols,
            "unmatched_bse_codes": self.unmatched_bse_codes,
            "bse_without_nse_listing": self.bse_without_nse_listing,
        }


@dataclass
class SyncOutcome:
    run_id: uuid.UUID | None
    kind: str
    status: str
    requests_made: int = 0
    records_attempted: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    failures: int = 0
    error_summary: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["run_id"] = str(self.run_id) if self.run_id else None
        return data


@dataclass
class _Progress:
    attempted: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    failures: int = 0
    skipped_points: int = 0
    periods: dict[str, str] = field(default_factory=dict)
    weekly_fallbacks: list[str] = field(default_factory=list)
    no_data: list[str] = field(default_factory=list)
    large_price_moves: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    ignored_bars: list[dict[str, str]] = field(default_factory=list)

    def record_ignored_bar(self, symbol: str, trade_date: date, reason: str) -> None:
        if len(self.ignored_bars) < MAX_ERRORS_RECORDED:
            self.ignored_bars.append({"symbol": symbol, "trade_date": trade_date.isoformat(), "reason": reason})

    def record_failure(self, symbol: str, error: MarketDataError) -> None:
        self.failures += 1
        if len(self.errors) < MAX_ERRORS_RECORDED:
            self.errors.append({"symbol": symbol, "error": type(error).__name__, "message": _truncate(str(error), 300)})

    def record_series(self, series: DailyPriceSeries, period: str, counts: repository.UpsertCounts) -> None:
        self.inserted += counts.inserted
        self.updated += counts.updated
        self.unchanged += counts.unchanged
        self.skipped_points += series.skipped_points
        self.periods[series.symbol] = period
        if not series.bars:
            self.no_data.append(series.symbol)
        self.large_price_moves.extend(_large_price_moves(series))

    def as_details(self) -> dict[str, Any]:
        return {
            "prices_unchanged": self.unchanged,
            "skipped_price_points": self.skipped_points,
            "periods": self.periods,
            "weekly_fallbacks": self.weekly_fallbacks,
            "no_data": self.no_data,
            "large_price_moves": self.large_price_moves,
            "ignored_bars": self.ignored_bars,
            "errors": self.errors,
        }


@contextmanager
def sync_lock(engine: Engine) -> Iterator[None]:
    """Session-level PostgreSQL advisory lock; raises if another sync holds it."""
    with engine.connect() as connection:
        acquired = connection.execute(select(func.pg_try_advisory_lock(SYNC_LOCK_ID))).scalar()
        if not acquired:
            raise SyncAlreadyRunningError("Another market-data sync is already running.")
        try:
            yield
        finally:
            connection.execute(select(func.pg_advisory_unlock(SYNC_LOCK_ID)))


# --- Security master -------------------------------------------------------------------


def sync_security_master(
    session_factory: sessionmaker[Session],
    engine: Engine,
    provider: MarketDataProvider,
    *,
    clock: Clock = now_utc,
) -> SyncOutcome:
    now = clock()
    with sync_lock(engine), session_factory() as session:
        run = _start_run(session, provider.name, KIND_SECURITY_MASTER, now)
        try:
            snapshot = provider.get_security_master()
            active = repository.count_active_listings(session, provider.name)
            if active and Decimal(len(snapshot.records)) < Decimal(active) * MIN_MASTER_RETENTION:
                raise ProviderResponseError(
                    f"security master: received {len(snapshot.records)} usable securities but {active} are active; "
                    "refusing to deactivate most listings."
                )
            counts, deactivated = repository.replace_security_master(
                session, provider.name, snapshot.records, seen_at=now
            )
            details = {
                "unmetered_requests": 1,
                "usable_securities": len(snapshot.records),
                "dropped_rows": snapshot.dropped_rows,
                "ambiguous_nse_symbols": list(snapshot.ambiguous_nse_symbols[:20]),
                "ambiguous_nse_symbol_count": len(snapshot.ambiguous_nse_symbols),
                "ambiguous_bse_codes": list(snapshot.ambiguous_bse_codes[:20]),
                "ambiguous_bse_code_count": len(snapshot.ambiguous_bse_codes),
                "deactivated": deactivated,
            }
            return _finish_run(
                session,
                run,
                clock,
                status="succeeded",
                attempted=len(snapshot.records),
                inserted=counts.inserted,
                updated=counts.updated,
                details=details,
            )
        except MarketDataError as exc:
            session.rollback()
            logger.warning("Security master sync failed: %s", exc)
            return _finish_run(session, run, clock, status="failed", error=str(exc), details={"unmetered_requests": 1})
        except Exception:
            session.rollback()
            _finish_run(session, run, clock, status="failed", error="Unexpected error during the security master sync; see server logs.")
            raise


# --- Daily prices ----------------------------------------------------------------------


def plan_price_sync(
    session: Session,
    provider: str,
    settings: Settings,
    *,
    now: datetime,
    portfolio_id: uuid.UUID | None = None,
    force: bool = False,
    only_symbols: set[str] | None = None,
) -> PriceSyncPlan:
    """Decide which held NSE securities need a request, without calling the provider.

    Registered benchmark securities are included: a comparison is only honest if the
    benchmark's closes are as current as the portfolio's, and each costs the same single
    request per sync as any held security.
    """
    expected = latest_expected_session(now, settings.trading_calendar)
    keys = repository.held_security_keys(session, portfolio_id)
    nse_symbols = {code for exchange, code in keys if exchange is Exchange.NSE}
    benchmark_symbols = {item.nse_symbol for item in available_benchmarks() if item.exchange is Exchange.NSE}
    nse_symbols |= benchmark_symbols
    if only_symbols is not None:
        # An operator restricting the run to named securities, to spend as few metered
        # requests as possible.
        nse_symbols &= only_symbols
        benchmark_symbols &= only_symbols
        bse_codes = {code for exchange, code in keys if exchange is Exchange.BSE} & only_symbols
    bse_codes = {code for exchange, code in keys if exchange is Exchange.BSE}
    by_nse, by_bse = repository.listings_by_codes(session, provider, nse_symbols, bse_codes)

    targets: dict[uuid.UUID, Listing] = {listing.id: listing for listing in by_nse.values()}
    unmatched_bse: list[str] = []
    bse_only: list[str] = []
    for code in sorted(bse_codes):
        listing = by_bse.get(code)
        if listing is None:
            unmatched_bse.append(code)
        elif listing.nse_symbol is None:
            bse_only.append(code)
        else:
            targets[listing.id] = listing

    latest = repository.latest_trade_dates(session, targets.keys(), Exchange.NSE)
    session_cutoff = eod_available_at(expected)
    requests: list[PlannedRequest] = []
    up_to_date: list[str] = []
    already_requested: list[str] = []
    for listing in sorted(targets.values(), key=lambda item: item.nse_symbol or ""):
        symbol = listing.nse_symbol or ""
        last = latest.get(listing.id)
        if not force and last is not None and last >= expected:
            up_to_date.append(symbol)
            continue
        requested_at = listing.prices_last_requested_at
        if not force and requested_at is not None and requested_at >= session_cutoff:
            already_requested.append(symbol)
            continue
        needs_backfill = last is None or (expected - last).days > BACKFILL_GAP_DAYS
        period: HistoricalPeriod = settings.market_data_backfill_period if needs_backfill else "1m"
        requests.append(PlannedRequest(listing.id, symbol, period, last))

    return PriceSyncPlan(
        expected_session=expected,
        requests=requests,
        up_to_date=up_to_date,
        already_requested_this_session=already_requested,
        unmatched_nse_symbols=sorted(nse_symbols - by_nse.keys() - benchmark_symbols),
        unmatched_benchmark_symbols=sorted(benchmark_symbols - by_nse.keys()),
        unmatched_bse_codes=unmatched_bse,
        bse_without_nse_listing=bse_only,
    )


def sync_daily_prices(
    session_factory: sessionmaker[Session],
    engine: Engine,
    provider: MarketDataProvider,
    settings: Settings,
    *,
    clock: Clock = now_utc,
    portfolio_id: uuid.UUID | None = None,
    force: bool = False,
    dry_run: bool = False,
    only_symbols: set[str] | None = None,
) -> SyncOutcome:
    now = clock()
    if dry_run:
        with session_factory() as session:
            plan = plan_price_sync(
                session, provider.name, settings, now=now, portfolio_id=portfolio_id,
                force=force, only_symbols=only_symbols,
            )
        return SyncOutcome(run_id=None, kind=KIND_DAILY_PRICES, status="dry_run", details=plan.as_details())

    with sync_lock(engine), session_factory() as session:
        run = _start_run(session, provider.name, KIND_DAILY_PRICES, now)
        try:
            if repository.count_active_listings(session, provider.name) == 0:
                return _finish_run(
                    session,
                    run,
                    clock,
                    status="failed",
                    error="The security master has not been loaded. Run 'sync-listings' first.",
                )
            plan = plan_price_sync(
                session, provider.name, settings, now=now, portfolio_id=portfolio_id,
                force=force, only_symbols=only_symbols,
            )
            if not plan.requests:
                return _finish_run(
                    session,
                    run,
                    clock,
                    status="succeeded",
                    details={**plan.as_details(), "message": "No requests were needed."},
                )
            budget = RequestBudget(
                limit=settings.market_data_monthly_request_budget,
                used_before_run=repository.requests_used_since(session, provider.name, ist_month_start(now)),
            )
            return _execute_plan(session, run, clock, provider, plan, budget, settings.trading_calendar)
        except Exception:
            session.rollback()
            _finish_run(session, run, clock, status="failed", error="Unexpected error during the price sync; see server logs.")
            raise


def _execute_plan(
    session: Session,
    run: MarketDataSyncRun,
    clock: Clock,
    provider: MarketDataProvider,
    plan: PriceSyncPlan,
    budget: RequestBudget,
    calendar: TradingCalendar,
) -> SyncOutcome:
    progress = _Progress()
    stop_status: str | None = None
    stop_error: str | None = None
    consecutive_rejections = 0
    provider.set_request_guard(budget.consume)
    try:
        for planned in plan.requests:
            progress.attempted += 1
            try:
                series, period = _fetch_series(provider, planned, progress)
            except (ProviderAuthenticationError, ProviderNotConfiguredError) as exc:
                stop_status, stop_error = "failed", str(exc)
            except ProviderRateLimitError as exc:
                stop_status, stop_error = "rate_limited", str(exc)
            except RequestBudgetExceededError as exc:
                progress.attempted -= 1  # the request was never sent
                stop_status, stop_error = "budget_exhausted", str(exc)
            except ProviderUnavailableError as exc:
                progress.record_failure(planned.nse_symbol, exc)
                stop_status, stop_error = "failed", str(exc)
            except (ProviderRequestError, ProviderResponseError) as exc:
                progress.record_failure(planned.nse_symbol, exc)
                status = "not_found" if isinstance(exc, ProviderNotFoundError) else "invalid_response"
                repository.mark_price_request(session, planned.listing_id, requested_at=clock(), status=status)
                logger.warning("Price sync for %s failed: %s", planned.nse_symbol, exc)
                if not isinstance(exc, ProviderNotFoundError):
                    consecutive_rejections += 1
                    if consecutive_rejections >= MAX_CONSECUTIVE_REJECTIONS:
                        stop_status = "failed"
                        stop_error = (
                            f"Stopped after {consecutive_rejections} consecutive rejected or invalid provider "
                            "responses; the provider may be failing every request."
                        )
            else:
                consecutive_rejections = 0
                series = _completed_session_closes(series, plan.expected_session, calendar, progress)
                fetched_at = clock()
                counts = repository.upsert_daily_prices(
                    session,
                    listing_id=planned.listing_id,
                    exchange=series.exchange,
                    bars=series.bars,
                    source=provider.name,
                    fetched_at=fetched_at,
                    sync_run_id=run.id,
                )
                progress.record_series(series, period, counts)
                repository.mark_price_request(
                    session, planned.listing_id, requested_at=fetched_at, status="ok" if series.bars else "no_data"
                )
            _save_progress(session, run, budget, progress, plan)
            if stop_status is not None:
                logger.warning("Price sync stopped (%s): %s", stop_status, stop_error)
                break
    finally:
        provider.set_request_guard(None)

    status = stop_status or ("partial" if progress.failures else "succeeded")
    error = stop_error
    if error is None and progress.failures:
        error = f"{progress.failures} of {progress.attempted} securities could not be updated."
    return _finish_run(
        session,
        run,
        clock,
        status=status,
        requests=budget.used_in_run,
        attempted=progress.attempted,
        inserted=progress.inserted,
        updated=progress.updated,
        failures=progress.failures,
        error=error,
        details={**plan.as_details(), **progress.as_details()},
    )


def _fetch_series(
    provider: MarketDataProvider,
    planned: PlannedRequest,
    progress: _Progress,
) -> tuple[DailyPriceSeries, HistoricalPeriod]:
    period = planned.period
    try:
        series = provider.get_daily_prices(planned.nse_symbol, period)
    except ProviderGranularityError:
        if period == "1m":
            raise
        logger.warning("%s: %s history is not confirmed daily; retrying with 1m.", planned.nse_symbol, period)
        progress.weekly_fallbacks.append(planned.nse_symbol)
        period = "1m"
        series = provider.get_daily_prices(planned.nse_symbol, period)
    if series.exchange is not Exchange.NSE or series.symbol != planned.nse_symbol:
        raise ProviderResponseError(
            f"historical prices for {planned.nse_symbol}: provider returned {series.exchange} prices for {series.symbol}."
        )
    return series, period


def _completed_session_closes(
    series: DailyPriceSeries,
    expected_session: date,
    calendar: TradingCalendar,
    progress: _Progress,
) -> DailyPriceSeries:
    """Keep only bars that are completed NSE session closes.

    A bar for the current session before its 18:00 IST availability, a future date, or a day
    that is not a session in the configured calendar is recorded in the run details and never
    stored, so it cannot be shown as an end-of-day close or overwrite an earlier close.
    """
    kept = []
    for bar in series.bars:
        if is_completed_session_close(bar.trade_date, expected_session, calendar):
            kept.append(bar)
        elif not calendar.is_session_day(bar.trade_date):
            progress.record_ignored_bar(series.symbol, bar.trade_date, "not_a_session_day")
        else:
            progress.record_ignored_bar(series.symbol, bar.trade_date, "session_not_complete")
    return series if len(kept) == len(series.bars) else replace(series, bars=tuple(kept))


def _large_price_moves(series: DailyPriceSeries) -> list[dict[str, str]]:
    """Day-over-day moves of 35% or more, which often indicate a split or bonus issue."""
    moves = []
    for previous, current in zip(series.bars, series.bars[1:], strict=False):
        change = (current.close_price - previous.close_price) / previous.close_price
        if abs(change) >= LARGE_MOVE_THRESHOLD:
            moves.append(
                {
                    "symbol": series.symbol,
                    "from": previous.trade_date.isoformat(),
                    "to": current.trade_date.isoformat(),
                    "change_pct": str((change * 100).quantize(Decimal("0.01"))),
                }
            )
    return moves


# --- Run bookkeeping -------------------------------------------------------------------


def _start_run(session: Session, provider: str, kind: str, now: datetime) -> MarketDataSyncRun:
    run = MarketDataSyncRun(provider=provider, kind=kind, status="running", started_at=now, details={})
    session.add(run)
    session.commit()
    return run


def _save_progress(
    session: Session,
    run: MarketDataSyncRun,
    budget: RequestBudget,
    progress: _Progress,
    plan: PriceSyncPlan,
) -> None:
    run.requests_made = budget.used_in_run
    run.records_attempted = progress.attempted
    run.records_inserted = progress.inserted
    run.records_updated = progress.updated
    run.failures = progress.failures
    run.details = {**plan.as_details(), **progress.as_details()}
    session.commit()


def _finish_run(
    session: Session,
    run: MarketDataSyncRun,
    clock: Clock,
    *,
    status: str,
    requests: int = 0,
    attempted: int = 0,
    inserted: int = 0,
    updated: int = 0,
    failures: int = 0,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> SyncOutcome:
    run.status = status
    run.completed_at = clock()
    run.requests_made = requests
    run.records_attempted = attempted
    run.records_inserted = inserted
    run.records_updated = updated
    run.failures = failures
    run.error_summary = _truncate(error, MAX_ERROR_SUMMARY_LENGTH) if error else None
    run.details = details or {}
    session.commit()
    return SyncOutcome(
        run_id=run.id,
        kind=run.kind,
        status=status,
        requests_made=requests,
        records_attempted=attempted,
        records_inserted=inserted,
        records_updated=updated,
        failures=failures,
        error_summary=run.error_summary,
        details=run.details,
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
