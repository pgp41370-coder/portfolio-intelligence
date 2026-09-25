"""Deterministic portfolio intelligence: a rendering of numbers computed elsewhere.

This layer explains; it does not calculate. Every figure it reports comes from the existing
performance, attribution, P&L and allocation services, and every sentence it writes is a
template filled with one of those figures. There is no model, no estimate and no forecast.

Three rules govern what it may say:

1. **State measurements, never judgements.** "HDFCBANK contributed -13.04 percentage points" is
   a fact. "HDFCBANK is a weak holding" is an opinion, and this application has no basis for
   one. Nothing here recommends buying, selling or holding anything.
2. **Never explain past the data.** A contribution says which security moved the portfolio, not
   why the security moved. The application knows the first and not the second.
3. **Disclose what qualifies the answer.** Stale prices, missing sessions, an unsynced
   benchmark and a ledger that disagrees with the holdings all change what the numbers mean, so
   they travel with them rather than being left for the reader to discover.

The findings are ordered by how much they change the reading - data quality first, because a
figure measured on stale prices should be read differently from a current one.
"""

import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.performance import risk as risk_metrics
from app.performance.allocation_service import build_allocation
from app.performance.attribution import attribute
from app.performance.calculations import (
    ValuePoint,
    as_percent,
    chain,
    flow_adjusted_returns,
    growth_index,
)
from app.performance.ledger_analysis import PerformanceContext, build_context
from app.performance.ledger_views import build_pnl
from app.performance.schemas import (
    AllocationRead,
    CalculationMethod,
    CashFlowExplanationRead,
    ContributorRead,
    CoverageStatus,
    DataQualityRead,
    HistoryBasis,
    IntelligenceStatus,
    MoneyWeightedRead,
    PeriodRead,
    PortfolioIntelligenceRead,
    PortfolioPerformanceRead,
    ReconciliationStatus,
    ReturnExplanationRead,
    RiskExplanationRead,
    TraceEntryRead,
)
from app.performance.service import build_performance
from app.portfolios.rules import Exchange

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)
_HUNDRED = Decimal(100)

DEFAULT_TOP_N = 3

METHODOLOGY = (
    "Every figure here is taken from the performance, attribution, profit-and-loss and "
    "allocation calculations, which read stored NSE end-of-day closes only. The text is a "
    "template filled with those figures. Nothing is modelled, extrapolated or inferred beyond "
    "what was measured, and nothing here is investment advice."
)

NO_DATA_NOTE = (
    "There is not enough priced history to explain anything yet. At least two completely "
    "priced sessions are needed before a return can be measured."
)


def build_intelligence(
    session: Session,
    portfolio_id: uuid.UUID,
    *,
    settings: Settings,
    now: datetime,
    start: date | None = None,
    end: date | None = None,
    benchmark: str | None = None,
    top: int = DEFAULT_TOP_N,
    trace: bool = False,
) -> PortfolioIntelligenceRead:
    # One valuation pass for the whole request: performance, attribution and P&L all read it.
    context: PerformanceContext = build_context(
        session, portfolio_id, settings=settings, now=now, start=start, end=end
    )
    portfolio, events, valued = context.portfolio, context.events, context.valuation

    performance = build_performance(
        session, portfolio_id, settings=settings, now=now, start=start, end=end,
        benchmark=benchmark, context=context,
    )
    allocation = build_allocation(session, portfolio_id, settings=settings, now=now)

    coverage = performance.coverage
    quality_limitations: list[str] = []
    if valued.is_empty:
        return PortfolioIntelligenceRead(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.name,
            as_of=now,
            status=IntelligenceStatus.UNAVAILABLE,
            period=performance.period,
            headline=NO_DATA_NOTE,
            findings=[],
            returns=None,
            money_weighted=None,
            cash_flow=None,
            risk=None,
            data_quality=_data_quality(
                performance, allocation, IntelligenceStatus.UNAVAILABLE, [], [NO_DATA_NOTE]
            ),
            methodology=METHODOLOGY,
        )

    points = [ValuePoint(day, total) for day, total in zip(valued.sessions, valued.totals, strict=True)]
    measured = flow_adjusted_returns(points, adjacent=valued.adjacent, flows=valued.flows)
    index_series = growth_index(points, measured.returns)
    window_return = chain(measured.returns)

    decomposition = attribute(
        sessions=valued.sessions,
        totals=valued.totals,
        values=valued.values,
        flows=valued.security_flows,
        adjacent=valued.adjacent,
    )
    contributors = [
        _contributor(item, rank, valued) for rank, item in enumerate(decomposition.positive, start=1)
    ]
    detractors = [
        _contributor(item, rank, valued)
        for rank, item in enumerate(sorted(decomposition.negative, key=lambda x: (x.contribution, x.key)), start=1)
    ]
    movers = [
        ContributorRead(
            rank=rank,
            symbol=item.key[0],
            exchange=Exchange(item.key[1]),
            contribution_pct=as_percent(item.contribution) or Decimal(0),
            security_return_pct=None,
            start_value=None,
            end_value=None,
            net_flow=item.cash_flow,
            start_weight_pct=None,
            end_weight_pct=None,
            sessions_counted=1,
        )
        for rank, item in enumerate(decomposition.latest, start=1)
    ]

    stale = sorted(
        f"{key[0]} on {key[1]}"
        for key, series in valued.closes.items()
        if series and max(series) < (coverage.latest_expected_session or max(series))
    )
    excluded = sorted(f"{item.symbol} on {item.exchange.value}" for item in performance.excluded_holdings)

    anomalies = performance.price_anomalies
    if anomalies is not None and anomalies.detected:
        quality_limitations.append(anomalies.note or "")
        quality_limitations.extend(item.description for item in anomalies.anomalies[:3])

    if coverage.sessions_behind_latest:
        quality_limitations.append(
            f"The newest stored close is {coverage.sessions_behind_latest} session"
            f"{'s' if coverage.sessions_behind_latest != 1 else ''} behind the latest completed NSE session."
        )
    if coverage.status is CoverageStatus.PARTIAL:
        quality_limitations.append(
            f"{coverage.missing_session_count} expected session"
            f"{'s' if coverage.missing_session_count != 1 else ''} could not be valued and "
            "were excluded; returns are never linked across them."
        )
    if performance.benchmark.status not in {"available", "not_requested"}:
        # Only a benchmark that was asked for and could not be provided qualifies the answer;
        # not asking for one does not.
        quality_limitations.append(f"No benchmark comparison: {performance.benchmark.note}")
    if performance.reconciliation.status is ReconciliationStatus.DIFFERS:
        quality_limitations.append(
            "The transaction ledger and the holdings on record disagree, so the series and the "
            "valuation describe different positions."
        )
    if excluded:
        quality_limitations.append(f"Excluded for want of usable NSE prices: {', '.join(excluded)}.")

    status = (
        IntelligenceStatus.LIMITED
        if quality_limitations or coverage.status is not CoverageStatus.COMPLETE
        else IntelligenceStatus.AVAILABLE
    )

    returns = _returns(performance, decomposition, window_return, contributors, detractors, movers, top)
    cash_flow = _cash_flow(session, portfolio_id, settings, now, points, valued, window_return, context)
    risk = _risk(measured.returns, index_series, allocation, performance)
    data_quality = _data_quality(performance, allocation, status, stale, quality_limitations)
    data_quality.price_anomalies = anomalies

    return PortfolioIntelligenceRead(
        portfolio_id=portfolio.id,
        portfolio_name=portfolio.name,
        as_of=now,
        status=status,
        period=PeriodRead(start=valued.sessions[0], end=valued.sessions[-1]),
        headline=_headline(performance, window_return),
        findings=_findings(returns, cash_flow, risk, data_quality, performance.money_weighted),
        returns=returns,
        money_weighted=performance.money_weighted,
        cash_flow=cash_flow,
        risk=risk,
        data_quality=data_quality,
        trace=_trace(returns, cash_flow, risk, valued, decomposition) if trace else None,
        methodology=METHODOLOGY,
    )


# --- Sections ----------------------------------------------------------------------------------


def _returns(
    performance: PortfolioPerformanceRead,
    decomposition,
    window_return: Decimal | None,
    contributors: list[ContributorRead],
    detractors: list[ContributorRead],
    movers: list[ContributorRead],
    top: int,
) -> ReturnExplanationRead:
    benchmark_return = performance.benchmark.cumulative_return_pct
    relative = (
        as_percent(window_return) - benchmark_return
        if (window_return is not None and benchmark_return is not None)
        else None
    )
    total = sum((item.contribution_pct for item in contributors + detractors), Decimal(0))
    measured_sum = as_percent(decomposition.sum_of_daily_returns)
    # The parts must add up to the measured sum. This is an identity, not an approximation, so
    # it is asserted here as a fact the response carries rather than a claim the reader trusts.
    reconciles = measured_sum is not None and total.quantize(Decimal("0.01")) == measured_sum.quantize(Decimal("0.01"))

    return ReturnExplanationRead(
        portfolio_return_pct=as_percent(window_return),
        benchmark_return_pct=benchmark_return,
        relative_return_pct=relative,
        calculation_method=performance.methodology.calculation_method,
        basis=performance.basis,
        sum_of_contributions_pct=measured_sum,
        compounding_difference_pct=(
            as_percent(window_return) - measured_sum
            if (window_return is not None and measured_sum is not None)
            else None
        ),
        contributions_reconcile=reconciles,
        top_positive=contributors[:top],
        top_negative=detractors[:top],
        latest_session=decomposition.latest_date,
        latest_session_movers=movers[:top],
        note=(
            "A security's contribution is its value change with its own cash flow removed, over "
            "the portfolio's opening value that session. Contributions sum to the portfolio's "
            "daily return; the window total is their arithmetic sum, which differs from the "
            "compounded return. Because each day is weighed against the portfolio's size on "
            "that day, a security's contribution can differ in sign from its own price return."
        ),
    )


def _cash_flow(
    session: Session,
    portfolio_id: uuid.UUID,
    settings: Settings,
    now: datetime,
    points: list[ValuePoint],
    valued,
    window_return: Decimal | None,
    context: PerformanceContext,
) -> CashFlowExplanationRead:
    """Separate the money that was added from the performance of the money already there."""
    start_value, end_value = points[0].value, points[-1].value
    with localcontext(_CONTEXT):
        value_change = end_value - start_value
        net_flow = sum(valued.flows, Decimal(0))
        return_driven = value_change - net_flow
        share = (
            (abs(net_flow) / abs(value_change)) * _HUNDRED if value_change != 0 else None
        )

    has_ledger = context.has_ledger
    contributions = withdrawals = None
    if has_ledger:
        pnl = build_pnl(session, portfolio_id, settings=settings, now=now, context=context)
        if pnl.totals is not None:
            contributions, withdrawals = pnl.totals.contributions, pnl.totals.withdrawals

    note = (
        "A change in portfolio value is not a return: money paid in raises the value without "
        "earning anything. The time-weighted return removes each day's cash flow before "
        "measuring, which is why the two figures can point in opposite directions."
        if has_ledger
        else "This portfolio has no transaction ledger, so no cash flows are recorded and the "
        "change in value is entirely price movement of the holdings on record."
    )

    return CashFlowExplanationRead(
        start_value=start_value,
        end_value=end_value,
        value_change=value_change,
        contributions=contributions,
        withdrawals=withdrawals,
        net_external_flow=net_flow,
        return_driven_change=return_driven,
        flow_share_of_change_pct=share,
        twr_pct=as_percent(window_return),
        available=True,
        note=note,
    )


def _risk(
    returns: list[Decimal | None],
    index_series: list[ValuePoint],
    allocation: AllocationRead,
    performance: PortfolioPerformanceRead,
) -> RiskExplanationRead:
    counts = risk_metrics.session_counts(returns)
    drawdown_now = risk_metrics.current_drawdown([point.value for point in index_series])
    concentration = allocation.concentration

    return RiskExplanationRead(
        volatility_pct=performance.summary.volatility_pct,
        downside_volatility_pct=performance.risk.downside_volatility.value,
        max_drawdown_pct=performance.summary.max_drawdown_pct,
        current_drawdown_pct=as_percent(drawdown_now.value),
        positive_sessions=counts.positive,
        negative_sessions=counts.negative,
        flat_sessions=counts.flat,
        beta=performance.risk.beta.value,
        largest_position_symbol=concentration.top_holding.symbol if concentration.top_holding else None,
        largest_position_weight_pct=concentration.top_1_pct,
        top_3_weight_pct=concentration.top_3_pct,
        hhi=concentration.hhi,
        concentration_band=concentration.hhi_band,
        effective_holdings=concentration.effective_holdings,
        note=(
            "Volatility and drawdown are measured on the growth index built from daily returns, "
            "so cash flows never register as performance. Concentration uses the latest stored "
            "closes. These are measurements, not an assessment of whether the portfolio is "
            "suitable for anyone."
        ),
    )


def _data_quality(
    performance: PortfolioPerformanceRead,
    allocation: AllocationRead,
    status: IntelligenceStatus,
    stale: list[str],
    limitations: list[str],
) -> DataQualityRead:
    coverage = performance.coverage
    unpriced = sorted(f"{item.symbol} on {item.exchange.value}" for item in allocation.unpriced_positions)
    return DataQualityRead(
        status=status,
        coverage_status=coverage.status,
        sessions_available=coverage.sessions_available,
        sessions_expected=coverage.sessions_expected,
        sessions_behind_latest=coverage.sessions_behind_latest,
        latest_expected_session=coverage.latest_expected_session,
        missing_session_count=coverage.missing_session_count,
        stale_securities=stale,
        excluded_securities=unpriced,
        benchmark_status=performance.benchmark.status,
        benchmark_basis=performance.benchmark.basis,
        reconciliation_status=performance.reconciliation.status,
        limitations=limitations,
        note=(
            "Nothing is interpolated, carried forward or substituted with zero. A session that "
            "could not be fully priced is excluded and counted, and staleness is reported "
            "separately from missing data."
        ),
    )


def _traced(value) -> str | None:
    """Render a traced figure exactly as the API publishes it, to 2 decimal places."""
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal("0.01")))


def _trace(
    returns: ReturnExplanationRead,
    cash_flow: CashFlowExplanationRead,
    risk: RiskExplanationRead,
    valued,
    decomposition,
) -> list[TraceEntryRead]:
    """Provenance for each headline figure: what produced it, from what, by what formula."""
    entries = [
        TraceEntryRead(
            metric="portfolio_return_pct",
            value=_traced(returns.portfolio_return_pct),
            source="performance.calculations.flow_adjusted_returns -> chain",
            inputs={
                "sessions_valued": str(len(valued.sessions)),
                "start_value": _traced(cash_flow.start_value),
                "end_value": _traced(cash_flow.end_value),
                "net_external_flow": _traced(cash_flow.net_external_flow),
            },
            formula="R_t = (V_t - CF_t) / V_(t-1) - 1, chained over adjacent sessions",
        ),
        TraceEntryRead(
            metric="sum_of_contributions_pct",
            value=_traced(returns.sum_of_contributions_pct),
            source="performance.attribution.attribute",
            inputs={
                "securities": str(len(valued.values)),
                "sessions_counted": str(decomposition.sessions_counted),
            },
            formula="c(i,t) = (V(i,t) - V(i,t-1) - CF(i,t)) / V(t-1), summed",
        ),
        TraceEntryRead(
            metric="return_driven_change",
            value=_traced(cash_flow.return_driven_change),
            source="performance.intelligence._cash_flow",
            inputs={
                "value_change": _traced(cash_flow.value_change),
                "net_external_flow": _traced(cash_flow.net_external_flow),
            },
            formula="(end value - start value) - net external flow",
        ),
        TraceEntryRead(
            metric="max_drawdown_pct",
            value=_traced(risk.max_drawdown_pct),
            source="performance.calculations.growth_index -> max_drawdown",
            inputs={"index_base": "100", "sessions_valued": str(len(valued.sessions))},
            formula="min over t of (I_t / max(I_0..I_t) - 1), on the growth index",
        ),
        TraceEntryRead(
            metric="current_drawdown_pct",
            value=_traced(risk.current_drawdown_pct),
            source="performance.risk.current_drawdown",
            inputs={"sessions_valued": str(len(valued.sessions))},
            formula="I_latest / max(I) - 1, on the growth index",
        ),
    ]
    for item in returns.top_positive + returns.top_negative:
        entries.append(
            TraceEntryRead(
                metric=f"contribution:{item.symbol}",
                value=_traced(item.contribution_pct),
                source="performance.attribution.attribute",
                inputs={
                    "start_value": _traced(item.start_value),
                    "end_value": _traced(item.end_value),
                    "net_flow": _traced(item.net_flow),
                    "sessions_counted": str(item.sessions_counted),
                },
                formula="sum over t of (V(i,t) - V(i,t-1) - CF(i,t)) / V(t-1)",
            )
        )
    return entries


# --- Sentences ------------------------------------------------------------------------------------
#
# Each of these is a template with measured numbers in it. They contain no adjectives about the
# securities themselves and no statement about what anyone should do.


def _headline(performance: PortfolioPerformanceRead, window_return: Decimal | None) -> str:
    measured = as_percent(window_return)
    if measured is None:
        return NO_DATA_NOTE
    basis = (
        "from recorded transactions"
        if performance.basis is HistoryBasis.TRANSACTIONS
        else "from today's holdings valued at past closes"
    )
    method = (
        "time-weighted return"
        if performance.methodology.calculation_method is CalculationMethod.TWR_DAILY_CHAINED
        else "price return"
    )
    sentence = f"Portfolio {method} was {_pct(measured)} over {performance.coverage.sessions_available} priced sessions, measured {basis}."
    benchmark = performance.benchmark
    if benchmark.status == "available" and benchmark.cumulative_return_pct is not None:
        relative = measured - benchmark.cumulative_return_pct
        direction = "ahead of" if relative > 0 else "behind" if relative < 0 else "level with"
        sentence += (
            f" That is {_points(abs(relative))} {direction} the benchmark proxy "
            f"({benchmark.display_name}), which returned {_pct(benchmark.cumulative_return_pct)}."
        )
    return sentence


def _findings(
    returns: ReturnExplanationRead,
    cash_flow: CashFlowExplanationRead,
    risk: RiskExplanationRead,
    quality: DataQualityRead,
    money_weighted: MoneyWeightedRead | None = None,
) -> list[str]:
    findings: list[str] = []

    # Data quality first: it changes how every other number should be read.
    for limitation in quality.limitations:
        findings.append(limitation)
    if quality.stale_securities:
        findings.append(
            f"Latest stored closes are older than the latest completed session for: "
            f"{', '.join(quality.stale_securities)}."
        )

    if returns.top_positive:
        best = returns.top_positive[0]
        findings.append(
            f"The largest positive contribution came from {best.symbol}: {_points(best.contribution_pct)}."
        )
    if returns.top_negative:
        worst = returns.top_negative[0]
        findings.append(
            f"The largest negative contribution came from {worst.symbol}: {_points(worst.contribution_pct)}."
        )
    if returns.relative_return_pct is not None:
        direction = (
            "ahead of" if returns.relative_return_pct > 0
            else "behind" if returns.relative_return_pct < 0
            else "level with"
        )
        findings.append(
            f"Relative to the benchmark proxy the portfolio is {_points(abs(returns.relative_return_pct))} {direction} it."
        )

    # The cash-flow point, stated only when flows actually moved the value.
    if cash_flow.net_external_flow and cash_flow.net_external_flow != 0 and cash_flow.value_change is not None:
        findings.append(
            f"Portfolio value changed by {_money(cash_flow.value_change)} while the time-weighted "
            f"return was {_pct(cash_flow.twr_pct) if cash_flow.twr_pct is not None else 'not measurable'}. "
            f"Net cash flow over the window was {_money(cash_flow.net_external_flow)}, so the change in "
            "value is not equivalent to investment performance."
        )

    if money_weighted is not None:
        findings.extend(_money_weighted_findings(returns, money_weighted))

    if risk.current_drawdown_pct is not None and risk.current_drawdown_pct < 0:
        findings.append(
            f"The portfolio is {_points(abs(risk.current_drawdown_pct))} below its highest measured level in this window."
        )
    if risk.positive_sessions or risk.negative_sessions:
        findings.append(
            f"{risk.positive_sessions} sessions gained, {risk.negative_sessions} lost and "
            f"{risk.flat_sessions} were unchanged."
        )
    if risk.largest_position_symbol and risk.largest_position_weight_pct is not None:
        findings.append(
            f"The largest position is {risk.largest_position_symbol} at "
            f"{_pct(risk.largest_position_weight_pct)} of priced value; the top three hold "
            f"{_pct(risk.top_3_weight_pct) if risk.top_3_weight_pct is not None else 'an unmeasured share'}."
        )
    return findings


def _money_weighted_findings(
    returns: ReturnExplanationRead, money_weighted: MoneyWeightedRead
) -> list[str]:
    """State both returns and the gap between them, without ranking the two measures."""
    if money_weighted.status == "not_applicable":
        return []
    if money_weighted.status == "ambiguous_multiple_roots":
        return [
            f"A money-weighted return is not being shown: {money_weighted.roots_found} different "
            "rates satisfy these cash flows, so no single figure can be stated."
        ]
    if money_weighted.period_pct is None:
        return [f"A money-weighted return could not be measured. {money_weighted.note}"]

    findings = []
    if returns.portfolio_return_pct is not None:
        difference = returns.portfolio_return_pct - money_weighted.period_pct
        findings.append(
            f"Over the same {money_weighted.period_days} days, the time-weighted return was "
            f"{_pct(returns.portfolio_return_pct)} and the money-weighted return was "
            f"{_pct(money_weighted.period_pct)}, a difference of "
            f"{_points(abs(difference))}. The two differ by the timing and size of the external "
            "cash flows, which the time-weighted return removes and the money-weighted return "
            "includes."
        )
    if money_weighted.annualised_pct is not None:
        findings.append(
            f"Annualised, the money-weighted return is {_pct(money_weighted.annualised_pct)}."
        )
    elif money_weighted.annualisation_note:
        findings.append(money_weighted.annualisation_note)
    if money_weighted.disclosure:
        findings.append(money_weighted.disclosure)
    return findings


def _contributor(item, rank: int, valued) -> ContributorRead:
    symbol, exchange = item.key
    flows = valued.security_flows.get(item.key, [])
    net_flow = sum(flows, Decimal(0))
    # The security's own return is a price return, taken from its first and last stored close
    # in the window. Its *value* also moves when shares are bought or sold, so value endpoints
    # would conflate the two.
    security_return = None
    closes = valued.closes.get(item.key) or {}
    priced_days = sorted(day for day in closes if valued.sessions[0] <= day <= valued.sessions[-1])
    if len(priced_days) >= 2 and closes[priced_days[0]] > 0:
        with localcontext(_CONTEXT):
            security_return = (closes[priced_days[-1]] / closes[priced_days[0]] - 1) * _HUNDRED

    return ContributorRead(
        rank=rank,
        symbol=symbol,
        exchange=Exchange(exchange),
        contribution_pct=as_percent(item.contribution) or Decimal(0),
        security_return_pct=security_return,
        start_value=item.start_value,
        end_value=item.end_value,
        net_flow=net_flow,
        start_weight_pct=as_percent(item.start_weight),
        end_weight_pct=as_percent(item.end_weight),
        sessions_counted=item.sessions_counted,
    )


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"


def _points(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    return f"{quantized} percentage point{'' if quantized == 1 else 's'}"


def _money(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    return f"{'-' if quantized < 0 else ''}INR {abs(quantized):,}"
