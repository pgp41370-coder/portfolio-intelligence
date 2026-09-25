"""Build a portfolio's historical value series and performance statistics.

Reads the database only. The portfolio's current holdings are valued at each completed NSE
session in the window: a session counts only when every priceable holding has a stored close,
so a partially priced day is reported missing instead of being valued as if a holding had
vanished. Nothing is interpolated or carried forward.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.market_data.calendar import latest_expected_session
from app.performance import benchmarks as benchmark_registry
from app.performance.calculations import (
    MIN_RETURNS_FOR_VOLATILITY,
    ReturnSkip,
    ValuePoint,
    annualised_volatility,
    as_percent,
    build_return_points,
    chain,
    cumulative_return,
    flow_adjusted_returns,
    growth_index,
    max_drawdown,
)
from app.performance.ledger_analysis import PerformanceContext, build_context
from app.performance.positions import LedgerEvent, SecurityKey, final_positions
from app.performance import corporate_actions
from app.performance import mwr as mwr_engine
from app.performance import risk as risk_metrics
from app.performance.schemas import (
    BenchmarkPointRead,
    BenchmarkRead,
    CalculationMethod,
    MeasureRead,
    MoneyWeightedRead,
    PriceAnomaliesRead,
    PriceAnomalyRead,
    RiskRead,
    CoverageRead,
    CoverageStatus,
    ExcludedHoldingRead,
    HistoryBasis,
    MAX_LISTED_MISSING_SESSIONS,
    PerformanceMethodologyRead,
    PeriodRead,
    PortfolioPerformanceRead,
    PositionDifferenceRead,
    ReconciliationRead,
    ReconciliationStatus,
    SeriesPointRead,
    SummaryRead,
    TRANSACTION_METHODOLOGY_NOTE,
)
from app.portfolios.models import Holding
from app.portfolios.rules import Exchange

MIN_POINTS_FOR_RETURNS = 2


def build_performance(
    session: Session,
    portfolio_id: uuid.UUID,
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
    benchmark: str | None = None,
    context: PerformanceContext | None = None,
) -> PortfolioPerformanceRead:
    """Historical performance on the best basis the stored data supports.

    A portfolio with a transaction ledger is measured from the position that ledger implies,
    with time-weighted returns. Without one, the M4.1 reconstruction of today's holdings
    applies, unchanged.

    ``context`` lets a caller that has already valued this portfolio hand the work over rather
    than paying for it twice. It must have been built for the same window.
    """
    context = context or build_context(session, portfolio_id, settings=settings, now=now, start=start, end=end)
    if context.has_ledger:
        return build_transaction_performance(
            session,
            portfolio_id,
            context.events,
            settings=settings,
            now=now,
            start=start,
            end=end,
            benchmark=benchmark,
            context=context,
        )
    return _build_holdings_performance(
        session, portfolio_id, settings=settings, now=now, start=start, end=end,
        benchmark=benchmark, context=context,
    )


def _build_holdings_performance(
    session: Session,
    portfolio_id: uuid.UUID,
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
    benchmark: str | None = None,
    context: PerformanceContext | None = None,
) -> PortfolioPerformanceRead:
    # The same valuation the rest of the request uses. It was extracted so that this card and
    # the explanation built from it can never describe different sessions.
    context = context or build_context(session, portfolio_id, settings=settings, now=now, start=start, end=end)
    portfolio = context.portfolio
    calendar = settings.trading_calendar
    valued = context.valuation
    excluded = valued.excluded
    window_end_cap = valued.window_end_cap

    if not valued.closes:
        return _empty(portfolio, now, start, window_end_cap, excluded, benchmark, session, settings,
                      note="No holding in this portfolio has stored end-of-day prices.")
    if valued.is_empty:
        return _empty(portfolio, now, valued.window_start, valued.window_end, excluded, benchmark, session, settings,
                      note="The requested window contains no completed session with stored prices.")

    window_start, window_end = valued.window_start, valued.window_end
    expected_sessions = valued.expected_sessions
    missing, missing_without_any_price = valued.missing, valued.missing_without_any_price
    points = [ValuePoint(day, total) for day, total in zip(valued.sessions, valued.totals, strict=True)]
    enriched = build_return_points(points, adjacent=valued.adjacent)
    returns = [point.daily_return for point in enriched]
    returns_used = sum(1 for value in returns if value is not None)
    skipped = sum(1 for index in range(1, len(points)) if not valued.adjacent[index])

    volatility = annualised_volatility(returns)
    volatility_note = (
        None if volatility is not None
        else f"Needs at least {MIN_RETURNS_FOR_VOLATILITY} daily returns; {returns_used} available."
    )
    summary = SummaryRead(
        start_value=points[0].value if points else None,
        end_value=points[-1].value if points else None,
        cumulative_return_pct=as_percent(cumulative_return(points[0].value, points[-1].value)) if len(points) >= MIN_POINTS_FOR_RETURNS else None,
        volatility_pct=as_percent(volatility),
        max_drawdown_pct=as_percent(max_drawdown(points)) if len(points) >= MIN_POINTS_FOR_RETURNS else None,
        returns_used=returns_used,
        returns_skipped_across_gaps=skipped,
        volatility_note=volatility_note,
    )
    coverage = _coverage(expected_sessions, points, missing, missing_without_any_price)
    _note_calendar_gap(coverage, calendar, window_start, window_end)
    _note_staleness(coverage, calendar, window_end, window_end_cap)
    portfolio_return = cumulative_return(points[0].value, points[-1].value) if len(points) >= MIN_POINTS_FOR_RETURNS else None
    benchmark_read, benchmark_returns = _benchmark(session, settings, benchmark, points, portfolio_return)

    return PortfolioPerformanceRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        as_of=now,
        basis=HistoryBasis.CURRENT_HOLDINGS,
        period=PeriodRead(start=points[0].trade_date if points else window_start, end=points[-1].trade_date if points else window_end),
        coverage=coverage,
        summary=summary,
        series=[
            SeriesPointRead(
                trade_date=point.trade_date,
                value=point.value,
                daily_return_pct=as_percent(point.daily_return),
                cumulative_return_pct=as_percent(point.cumulative_return) or Decimal(0),
            )
            for point in enriched
        ],
        benchmark=benchmark_read,
        price_anomalies=_price_anomalies(valued),
        money_weighted=MoneyWeightedRead(
            status=mwr_engine.MoneyWeightedStatus.NOT_APPLICABLE,
            note=(
                "A money-weighted return needs recorded cash flows. This portfolio has no "
                "transaction ledger, so there is nothing to measure the timing of."
            ),
        ),
        risk=_risk(
            returns,
            benchmark_returns,
            volatility=volatility,
            max_drawdown_value=max_drawdown(points) if len(points) >= MIN_POINTS_FOR_RETURNS else None,
            cumulative=portfolio_return,
            excess=_excess(portfolio_return, benchmark_read),
            settings=settings,
            years=_years(points),
        ),
        excluded_holdings=excluded,
        methodology=PerformanceMethodologyRead(basis=HistoryBasis.CURRENT_HOLDINGS),
    )


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _coverage(
    expected: list[date],
    points: list[ValuePoint],
    missing: list[date],
    missing_without_any_price: list[date],
) -> CoverageRead:
    if len(points) < MIN_POINTS_FOR_RETURNS:
        status = CoverageStatus.INSUFFICIENT
    elif missing:
        status = CoverageStatus.PARTIAL
    else:
        status = CoverageStatus.COMPLETE

    note = None
    if status is CoverageStatus.INSUFFICIENT:
        note = "At least two completely priced sessions are needed to measure a return."
    elif status is CoverageStatus.PARTIAL:
        parts = ["Sessions without a complete set of closes are excluded; returns are not linked across them."]
        if missing_without_any_price:
            parts.append(
                f"{len(missing_without_any_price)} of them have no price for any holding, which usually means an "
                "exchange holiday the configured calendar does not list, or a sync that failed for every security."
            )
        partial_count = len(missing) - len(missing_without_any_price)
        if partial_count:
            parts.append(f"{partial_count} have prices for only some holdings.")
        note = " ".join(parts)

    return CoverageRead(
        status=status,
        sessions_expected=len(expected),
        sessions_available=len(points),
        missing_sessions=missing[:MAX_LISTED_MISSING_SESSIONS],
        missing_session_count=len(missing),
        missing_no_prices_at_all_count=len(missing_without_any_price),
        missing_some_prices_count=len(missing) - len(missing_without_any_price),
        coverage_pct=as_percent(Decimal(len(points)) / Decimal(len(expected))) if expected else None,
        note=note,
    )


def _benchmark(
    session: Session,
    settings: Settings,
    requested: str | None,
    points: list[ValuePoint],
    portfolio_return: Decimal | None,
) -> tuple[BenchmarkRead, list[Decimal | None]]:
    """Compare against a benchmark, or say plainly why there is no comparison.

    Also returns the benchmark's daily returns aligned to ``points``, so risk measures can be
    computed from exactly the sessions both series priced.
    """
    empty_returns: list[Decimal | None] = [None] * len(points)
    if not requested:
        return (
            BenchmarkRead(
                requested=None,
                status=benchmark_registry.BenchmarkStatus.NOT_REQUESTED,
                note="No benchmark was requested.",
            ),
            empty_returns,
        )

    definition = benchmark_registry.get_benchmark(requested)
    if definition is None:
        status = (
            benchmark_registry.BenchmarkStatus.NOT_CONFIGURED
            if not benchmark_registry.BENCHMARKS
            else benchmark_registry.BenchmarkStatus.UNKNOWN_KEY
        )
        note = (
            benchmark_registry.NOT_CONFIGURED_NOTE
            if status == benchmark_registry.BenchmarkStatus.NOT_CONFIGURED
            else f"No benchmark is registered under the key {requested!r}."
        )
        return BenchmarkRead(requested=requested, status=status, note=note), empty_returns

    described = {
        "requested": requested,
        "display_name": definition.display_name,
        "basis": definition.basis,
        "tracks": definition.tracks,
        "source": definition.source,
        "is_proxy": definition.is_proxy,
        "methodology": definition.methodology,
    }
    closes = benchmark_registry.benchmark_closes(
        session,
        settings.market_data_provider,
        definition,
        start=points[0].trade_date if points else None,
        end=points[-1].trade_date if points else None,
    )
    # Compare only on sessions the portfolio itself was valued on; never fill the others.
    aligned = [closes.get(point.trade_date) for point in points]
    shared = [(point, close) for point, close in zip(points, aligned, strict=True) if close is not None]
    if len(shared) < MIN_POINTS_FOR_RETURNS:
        return (
            BenchmarkRead(
                **described,
                status=benchmark_registry.BenchmarkStatus.NO_DATA,
                sessions_compared=len(shared),
                note=benchmark_registry.NO_DATA_NOTE,
            ),
            empty_returns,
        )

    first_close = shared[0][1]
    benchmark_return = cumulative_return(first_close, shared[-1][1])
    excess = (
        (portfolio_return - benchmark_return)
        if (portfolio_return is not None and benchmark_return is not None)
        else None
    )
    series = [
        BenchmarkPointRead(trade_date=point.trade_date, index=(close / first_close) * Decimal(100))
        for point, close in shared
    ]
    # A benchmark return needs two consecutive sessions that both priced, exactly like the
    # portfolio's: a day either series missed produces no return, not an interpolated one.
    returns: list[Decimal | None] = [None]
    for index in range(1, len(points)):
        previous, current = aligned[index - 1], aligned[index]
        returns.append(
            current / previous - 1 if (previous is not None and current is not None and previous > 0) else None
        )

    return (
        BenchmarkRead(
            **described,
            status=benchmark_registry.BenchmarkStatus.AVAILABLE,
            cumulative_return_pct=as_percent(benchmark_return),
            excess_return_pct=as_percent(excess),
            sessions_compared=len(shared),
            series=series,
            note=definition.note,
        ),
        returns,
    )


def _risk(
    portfolio_returns: list[Decimal | None],
    benchmark_returns: list[Decimal | None],
    *,
    volatility: Decimal | None,
    max_drawdown_value: Decimal | None,
    cumulative: Decimal | None,
    excess: Decimal | None,
    settings: Settings,
    years: Decimal | None,
) -> RiskRead:
    """Assemble the risk block, withholding any measure whose data requirement is unmet."""
    paired_portfolio, paired_benchmark = risk_metrics.paired_returns(portfolio_returns, benchmark_returns)
    tracking = risk_metrics.tracking_error(paired_portfolio, paired_benchmark)
    return RiskRead(
        volatility_pct=as_percent(volatility),
        downside_volatility=_measure(risk_metrics.downside_volatility(portfolio_returns), as_pct=True),
        max_drawdown_pct=as_percent(max_drawdown_value),
        beta=_measure(risk_metrics.beta(paired_portfolio, paired_benchmark), as_pct=False),
        tracking_error_pct=_measure(tracking, as_pct=True),
        information_ratio=_measure(
            risk_metrics.information_ratio(excess, tracking), as_pct=False
        ),
        sharpe_ratio=_measure(
            risk_metrics.sharpe_ratio(
                cumulative, volatility, risk_free_rate=settings.risk_free_rate, years=years
            ),
            as_pct=False,
        ),
        observations=sum(1 for value in portfolio_returns if value is not None),
    )


def _measure(measure: risk_metrics.Measure, *, as_pct: bool) -> MeasureRead:
    value = as_percent(measure.value) if (as_pct and measure.value is not None) else measure.value
    return MeasureRead(value=value, available=measure.available, note=measure.note)


def _empty(
    portfolio,
    now: datetime,
    start: date | None,
    end: date | None,
    excluded: list[ExcludedHoldingRead],
    benchmark: str | None,
    session: Session,
    settings: Settings,
    *,
    note: str,
) -> PortfolioPerformanceRead:
    return PortfolioPerformanceRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        as_of=now,
        basis=HistoryBasis.CURRENT_HOLDINGS,
        period=PeriodRead(start=start, end=end),
        coverage=CoverageRead(
            status=CoverageStatus.INSUFFICIENT,
            sessions_expected=0,
            sessions_available=0,
            missing_sessions=[],
            missing_session_count=0,
            coverage_pct=None,
            note=note,
        ),
        summary=SummaryRead(
            start_value=None,
            end_value=None,
            cumulative_return_pct=None,
            volatility_pct=None,
            max_drawdown_pct=None,
            returns_used=0,
            returns_skipped_across_gaps=0,
            volatility_note=None,
        ),
        series=[],
        benchmark=_benchmark(session, settings, benchmark, [], None)[0],
        excluded_holdings=excluded,
        methodology=PerformanceMethodologyRead(basis=HistoryBasis.CURRENT_HOLDINGS),
    )


# --- Transaction basis ----------------------------------------------------------------------
#
# The position on each session comes from the ledger, so the series is what the portfolio was
# actually worth. Returns are time-weighted: the day's external cash flow is removed before the
# return is taken, which is what separates performance from the effect of adding money.


def build_transaction_performance(
    session: Session,
    portfolio_id: uuid.UUID,
    events: list[LedgerEvent],
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
    benchmark: str | None = None,
    context: PerformanceContext | None = None,
) -> PortfolioPerformanceRead:
    context = context or build_context(session, portfolio_id, settings=settings, now=now, start=start, end=end)
    portfolio = context.portfolio
    calendar = settings.trading_calendar
    valued = context.valuation

    if valued.is_empty:
        return _empty(
            portfolio, now, valued.window_start, valued.window_end, valued.excluded, benchmark, session, settings,
            note="The requested window contains no completed session with stored prices.",
        )

    points = [ValuePoint(day, total) for day, total in zip(valued.sessions, valued.totals, strict=True)]
    measured = flow_adjusted_returns(points, adjacent=valued.adjacent, flows=valued.flows)
    index_series = growth_index(points, measured.returns)
    twr = chain(measured.returns)

    volatility = annualised_volatility(measured.returns)
    volatility_note = (
        None if volatility is not None
        else f"Needs at least {MIN_RETURNS_FOR_VOLATILITY} daily returns; {measured.used} available."
    )
    net_flow = sum(valued.flows, Decimal(0))
    cumulative_by_point = _cumulative_from_index(index_series)

    summary = SummaryRead(
        start_value=points[0].value,
        end_value=points[-1].value,
        cumulative_return_pct=as_percent(twr),
        volatility_pct=as_percent(volatility),
        # Drawdown reads the growth index, not portfolio value: a withdrawal is not a loss.
        max_drawdown_pct=as_percent(max_drawdown(index_series)) if len(points) >= MIN_POINTS_FOR_RETURNS else None,
        returns_used=measured.used,
        returns_skipped_across_gaps=measured.skipped(ReturnSkip.GAP),
        returns_skipped_zero_base=measured.skipped(ReturnSkip.ZERO_BASE),
        net_external_flow=net_flow,
        volatility_note=volatility_note,
    )
    coverage = _coverage(valued.expected_sessions, points, valued.missing, valued.missing_without_any_price)
    _note_calendar_gap(coverage, calendar, valued.window_start, valued.window_end)
    _note_staleness(coverage, calendar, valued.window_end, valued.window_end_cap)
    if valued.empty_sessions:
        note = (
            f"{valued.empty_sessions} session(s) in this window had no holdings; the portfolio was "
            "empty, not unpriced."
        )
        coverage.note = f"{coverage.note} {note}" if coverage.note else note
    timeline = valued.timeline
    if timeline is not None and timeline.non_session_dates:
        dates = ", ".join(f"{day:%d %b %Y}" for day in sorted(set(timeline.non_session_dates))[:5])
        addition = (
            f"{len(set(timeline.non_session_dates))} transaction date(s) are not trading sessions "
            f"({dates}); each is recognised at the next session's close."
        )
        coverage.note = f"{coverage.note} {addition}" if coverage.note else addition

    benchmark_read, benchmark_returns = _benchmark(session, settings, benchmark, points, twr)

    return PortfolioPerformanceRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        as_of=now,
        basis=HistoryBasis.TRANSACTIONS,
        period=PeriodRead(start=points[0].trade_date, end=points[-1].trade_date),
        coverage=coverage,
        summary=summary,
        series=[
            SeriesPointRead(
                trade_date=point.trade_date,
                value=point.value,
                daily_return_pct=as_percent(change),
                cumulative_return_pct=as_percent(cumulative) or Decimal(0),
            )
            for point, change, cumulative in zip(points, measured.returns, cumulative_by_point, strict=True)
        ],
        benchmark=benchmark_read,
        money_weighted=_money_weighted(valued),
        price_anomalies=_price_anomalies(valued),
        risk=_risk(
            measured.returns,
            benchmark_returns,
            volatility=volatility,
            max_drawdown_value=max_drawdown(index_series) if len(points) >= MIN_POINTS_FOR_RETURNS else None,
            cumulative=twr,
            excess=_excess(twr, benchmark_read),
            settings=settings,
            years=_years(points),
        ),
        excluded_holdings=valued.excluded,
        reconciliation=_reconcile(events, portfolio.holdings),
        methodology=PerformanceMethodologyRead(
            basis=HistoryBasis.TRANSACTIONS,
            calculation_method=CalculationMethod.TWR_DAILY_CHAINED,
            note=TRANSACTION_METHODOLOGY_NOTE,
        ),
    )


def _price_anomalies(valued) -> PriceAnomaliesRead:
    """Scan the window's closes for moves large enough to distrust.

    Reuses the closes already loaded for the valuation: no extra query and no extra pass.
    """
    found = corporate_actions.detect_anomalies(valued.closes, window=valued.sessions or None)
    return PriceAnomaliesRead(
        detected=len(found),
        threshold_pct=corporate_actions.DEFAULT_THRESHOLD * Decimal(100),
        anomalies=[
            PriceAnomalyRead(
                symbol=item.symbol,
                exchange=Exchange(item.exchange),
                previous_date=item.previous_date,
                trade_date=item.trade_date,
                previous_close=item.previous_close,
                close=item.close,
                change_pct=item.change * Decimal(100),
                consistent_with=item.consistent_with,
                trigger=item.trigger,
                description=corporate_actions.describe(item),
            )
            for item in found[: corporate_actions.MAX_REPORTED]
        ],
        note=corporate_actions.consequence_note(len(found)) if found else None,
    )


SUB_WINDOW_DISCLOSURE = (
    "This window starts after the first transaction, so the position carried into it is valued "
    "at its market price on the first session rather than at what it cost. Transaction costs "
    "paid before the window are not attributed to it."
)


def _money_weighted(valued) -> MoneyWeightedRead:
    """Solve the investor's cash flows for a rate, reusing the valuation already computed.

    No extra valuation pass and no extra query: the sessions, the flows and the terminal value
    all come from the context, and the opening position is priced from closes already loaded.
    """
    opening_value = Decimal(0)
    timeline = valued.timeline
    if timeline is not None and timeline.opening and valued.sessions:
        first = valued.sessions[0]
        opening_value = sum(
            (
                Decimal(quantity) * valued.closes[key][first]
                for key, quantity in timeline.opening.items()
                if quantity and key in valued.closes and first in valued.closes[key]
            ),
            Decimal(0),
        )

    flows = mwr_engine.build_cash_flows(
        valued.sessions, valued.flows, valued.totals[-1] if valued.totals else Decimal(0),
        opening_value=opening_value,
    )
    result = mwr_engine.money_weighted_return(flows)
    return MoneyWeightedRead(
        status=result.status,
        annualised_pct=as_percent(result.annualised),
        period_pct=as_percent(result.period),
        period_days=result.days,
        annualisation_available=result.annualised is not None,
        contributions=result.contributions,
        withdrawals=result.withdrawals,
        terminal_value=result.terminal_value,
        roots_found=result.roots_found,
        opening_position_valued=opening_value > 0,
        note=result.note,
        annualisation_note=result.annualisation_note,
        disclosure=SUB_WINDOW_DISCLOSURE if opening_value > 0 else None,
    )


def _excess(portfolio_return: Decimal | None, benchmark: BenchmarkRead) -> Decimal | None:
    """The window's outperformance, as a fraction, when both sides measured one."""
    if portfolio_return is None or benchmark.excess_return_pct is None:
        return None
    return benchmark.excess_return_pct / Decimal(100)


def _years(points: list[ValuePoint]) -> Decimal | None:
    """Length of the window in years, for annualising a return. None below two sessions."""
    if len(points) < MIN_POINTS_FOR_RETURNS:
        return None
    days = (points[-1].trade_date - points[0].trade_date).days
    return Decimal(days) / Decimal(365) if days > 0 else None


def _note_staleness(coverage: CoverageRead, calendar, window_end: date, latest_expected: date) -> None:
    """Say how far behind the market the newest stored close leaves this window."""
    coverage.latest_expected_session = latest_expected
    if window_end >= latest_expected:
        return
    behind = sum(
        1 for day in _days(window_end, latest_expected) if day > window_end and calendar.is_session_day(day)
    )
    coverage.sessions_behind_latest = behind
    if not behind:
        return
    note = (
        f"Prices are behind the market: the latest completed NSE session is "
        f"{latest_expected:%d %b %Y}, but the newest stored close is {window_end:%d %b %Y} "
        f"({behind} session{'s' if behind != 1 else ''} behind). The window stops at the data "
        "rather than showing unpriced days."
    )
    coverage.note = f"{coverage.note} {note}" if coverage.note else note


def _note_calendar_gap(coverage: CoverageRead, calendar, start: date, end: date) -> None:
    """Say so when the window reaches outside the range the holiday list covers."""
    gap = calendar.completeness_gap(start, end)
    if gap:
        coverage.note = f"{coverage.note} {gap}" if coverage.note else gap


def _cumulative_from_index(index_series: list[ValuePoint]) -> list[Decimal]:
    """Cumulative time-weighted return at each point, from the base-100 growth index."""
    if not index_series:
        return []
    base = index_series[0].value
    return [(point.value / base - 1) if base > 0 else Decimal(0) for point in index_series]


def _reconcile(events: list[LedgerEvent], holdings: list[Holding]) -> ReconciliationRead:
    """Compare the ledger's final position with the holdings the user entered."""
    ledger = final_positions(events)
    declared: dict[SecurityKey, int] = {(item.symbol, item.exchange): item.quantity for item in holdings}
    differences = [
        PositionDifferenceRead(
            symbol=symbol,
            exchange=Exchange(exchange),
            ledger_quantity=ledger.get((symbol, exchange), 0),
            holdings_quantity=declared.get((symbol, exchange), 0),
        )
        for symbol, exchange in sorted(set(ledger) | set(declared))
        if ledger.get((symbol, exchange), 0) != declared.get((symbol, exchange), 0)
    ]
    if not differences:
        return ReconciliationRead(
            status=ReconciliationStatus.MATCHES,
            note="The transaction ledger's closing position matches the holdings on record.",
        )
    return ReconciliationRead(
        status=ReconciliationStatus.DIFFERS,
        differences=differences,
        note=(
            "The transaction ledger and the holdings on record disagree. Neither is changed "
            "automatically: the series uses the ledger, while valuation uses the holdings."
        ),
    )
