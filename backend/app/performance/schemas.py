"""Performance API response models.

Money and percentages are decimal strings, as elsewhere in the API. Anything unavailable is
null with a stated reason; it is never zero and never interpolated.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

from app.performance.calculations import TRADING_DAYS_PER_YEAR
from app.portfolios.rules import Exchange
from app.valuation.calculations import format_money, format_percent

Money = Annotated[Decimal, PlainSerializer(format_money, return_type=str)]
Percent = Annotated[Decimal, PlainSerializer(format_percent, return_type=str)]

MAX_LISTED_MISSING_SESSIONS = 30

METHODOLOGY_NOTE = (
    "Historical value of the portfolio's current holdings at dated NSE end-of-day closes. "
    "Holdings are assumed constant across the window because the system stores no transaction "
    "history, so this is a reconstruction, not a record of what was actually held. Excludes "
    "dividends, taxes and charges; not adjusted for corporate actions; not a total return. "
    "This is portfolio analytics, not personalized investment advice."
)
SHARPE_NOTE = "Deferred: no risk-free rate is configured, and assuming one would manufacture precision."

TRANSACTION_METHODOLOGY_NOTE = (
    "Portfolio value at dated NSE end-of-day closes, using the position implied by the recorded "
    "transactions on each session. Returns are time-weighted: each day's external cash flow is "
    "removed before the return is measured, so contributions and withdrawals do not count as "
    "performance. Transactions are recognised at the close of their trade date. Excludes dividends "
    "and corporate actions; not a total return. This is portfolio analytics, not personalized "
    "investment advice."
)


class HistoryBasis(StrEnum):
    CURRENT_HOLDINGS = "CURRENT_HOLDINGS"  # reconstruction from today's holdings
    TRANSACTIONS = "TRANSACTIONS"  # reserved for the transaction ledger (M4.2)


class CalculationMethod(StrEnum):
    """How the headline return was measured."""

    PRICE_RETURN_ENDPOINTS = "PRICE_RETURN_ENDPOINTS"  # end value over start value (no flows exist)
    TWR_DAILY_CHAINED = "TWR_DAILY_CHAINED"  # product of daily flow-adjusted returns


class ReconciliationStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"  # no ledger to compare
    MATCHES = "matches"
    DIFFERS = "differs"


class CoverageStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class ExcludedReason(StrEnum):
    LISTING_NOT_FOUND = "LISTING_NOT_FOUND"
    NO_NSE_LISTING = "NO_NSE_LISTING"
    NO_PRICE_DATA = "NO_PRICE_DATA"


class ExcludedHoldingRead(BaseModel):
    symbol: str
    exchange: Exchange
    reason: ExcludedReason


class PeriodRead(BaseModel):
    start: date | None
    end: date | None


class CoverageRead(BaseModel):
    """How much of the expected calendar could actually be valued.

    A session where no holding has a close is reported separately from one where only some
    do: the first usually means the exchange was closed on a day the configured calendar does
    not know about, or that a sync failed for every security, while the second is a genuine
    per-security gap. Neither is interpolated.
    """

    status: CoverageStatus
    sessions_expected: int
    sessions_available: int
    missing_sessions: list[date]
    missing_session_count: int
    missing_no_prices_at_all_count: int = 0
    missing_some_prices_count: int = 0
    coverage_pct: Percent | None
    # Sessions between the newest stored close and the latest completed NSE session. The
    # window stops at the data; this says how far behind the market that leaves it.
    sessions_behind_latest: int = 0
    latest_expected_session: date | None = None
    note: str | None = None


class SummaryRead(BaseModel):
    start_value: Money | None
    end_value: Money | None
    cumulative_return_pct: Percent | None
    volatility_pct: Percent | None
    max_drawdown_pct: Percent | None
    returns_used: int
    returns_skipped_across_gaps: int
    volatility_note: str | None = None
    # Transaction basis only: days with nothing held carry no return, and the flow total says
    # how much money entered or left the portfolio during the window.
    returns_skipped_zero_base: int = 0
    net_external_flow: Money | None = None


class PositionDifferenceRead(BaseModel):
    symbol: str
    exchange: Exchange
    ledger_quantity: int
    holdings_quantity: int


class ReconciliationRead(BaseModel):
    """Whether the ledger's final position agrees with the holdings the user entered.

    Neither source overrides the other: holdings stay the user's declared position and the
    ledger stays their record of trades. A difference is reported, never silently resolved.
    """

    status: ReconciliationStatus
    differences: list[PositionDifferenceRead] = []
    note: str | None = None


class SeriesPointRead(BaseModel):
    trade_date: date
    value: Money
    daily_return_pct: Percent | None
    cumulative_return_pct: Percent


# --- Risk and benchmark comparison (M4.2) -------------------------------------------------


class MeasureRead(BaseModel):
    """A statistic, or the reason it is not being shown."""

    value: Percent | None = None
    available: bool = False
    note: str | None = None


class RiskRead(BaseModel):
    volatility_pct: Percent | None = None
    downside_volatility: MeasureRead = MeasureRead()
    max_drawdown_pct: Percent | None = None
    beta: MeasureRead = MeasureRead()
    tracking_error_pct: MeasureRead = MeasureRead()
    information_ratio: MeasureRead = MeasureRead()
    sharpe_ratio: MeasureRead = MeasureRead()
    observations: int = 0
    note: str = (
        "Measured from daily returns between adjacent completed sessions only. Each measure "
        "states its own minimum data requirement and is withheld rather than estimated."
    )


class BenchmarkPointRead(BaseModel):
    trade_date: date
    index: Percent  # rebased to 100 at the window's first shared session


class BenchmarkRead(BaseModel):
    """A benchmark comparison, or an explicit statement that there is none.

    ``basis`` is ``ETF_PROXY`` when the series is an index ETF standing in for its index,
    which the note spells out. It is never presented as the index itself.
    """

    requested: str | None
    status: str
    display_name: str | None = None
    basis: str | None = None
    tracks: str | None = None
    source: str | None = None
    is_proxy: bool = False
    cumulative_return_pct: Percent | None = None
    excess_return_pct: Percent | None = None
    sessions_compared: int = 0
    series: list[BenchmarkPointRead] = []
    methodology: str | None = None
    note: str


class MoneyWeightedRead(BaseModel):
    """The investor's money-weighted return, or the reason there is not one.

    Reported beside the time-weighted return, never instead of it. The two answer different
    questions: TWR measures the portfolio with cash flows removed, MWR measures the investor
    including the timing and size of those flows. Neither is the better number; they are
    different measurements, and the response does not rank them.
    """

    status: str
    annualised_pct: Percent | None = None  # the XIRR itself
    period_pct: Percent | None = None  # restated over the window, comparable with a cumulative TWR
    period_days: int = 0
    annualisation_available: bool = False
    contributions: Money | None = None
    # Every positive cash flow in the XIRR, which by convention includes the closing terminal
    # value. It is therefore NOT the same quantity as the P&L payload's `withdrawals`, which
    # counts only money actually taken out. `terminal_value` below is reported separately so the
    # two parts can be told apart.
    withdrawals: Money | None = None
    terminal_value: Money | None = None
    roots_found: int = 0
    opening_position_valued: bool = False  # true for a window that starts mid-history
    note: str
    annualisation_note: str | None = None
    disclosure: str | None = None
    method: str = "XIRR_BISECTION_ACT365"


class PriceAnomalyRead(BaseModel):
    """A price move large enough that the figures built on it should not be trusted."""

    symbol: str
    exchange: Exchange
    previous_date: date
    trade_date: date
    previous_close: Money
    close: Money
    change_pct: Percent
    # What a corporate action of this size would look like, when the arithmetic is close.
    # Never a claim that one happened: the application has no corporate-action data.
    consistent_with: str | None
    trigger: str  # large_move, or corporate_action_ratio
    description: str


class PriceAnomaliesRead(BaseModel):
    """Moves in the window that may be corporate actions rather than price changes.

    Detected and disclosed, never adjusted for. Adjusting would need a ratio and an effective
    date the application does not have, and guessing them would rewrite the user's history.
    """

    detected: int
    threshold_pct: Percent
    anomalies: list[PriceAnomalyRead] = []
    note: str | None = None


class PerformanceMethodologyRead(BaseModel):
    basis: HistoryBasis
    calculation_method: CalculationMethod = CalculationMethod.PRICE_RETURN_ENDPOINTS
    price_basis: Literal["NSE_EOD_CLOSE"] = "NSE_EOD_CLOSE"
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR
    returns: str = "Daily simple returns between adjacent completed sessions; gaps are never linked across."
    sharpe: str = SHARPE_NOTE
    note: str = METHODOLOGY_NOTE


class PortfolioPerformanceRead(BaseModel):
    portfolio_id: uuid.UUID
    portfolio_name: str
    currency: Literal["INR"] = "INR"
    as_of: datetime
    basis: HistoryBasis
    period: PeriodRead
    coverage: CoverageRead
    summary: SummaryRead
    series: list[SeriesPointRead]
    benchmark: BenchmarkRead
    money_weighted: MoneyWeightedRead | None = None
    price_anomalies: PriceAnomaliesRead | None = None
    risk: RiskRead = Field(default_factory=RiskRead)
    excluded_holdings: list[ExcludedHoldingRead]
    reconciliation: ReconciliationRead = ReconciliationRead(status=ReconciliationStatus.NOT_APPLICABLE)
    methodology: PerformanceMethodologyRead


# --- Allocation and concentration (M4.2) -------------------------------------------------


class WeightRead(BaseModel):
    symbol: str
    exchange: Exchange
    market_value: Money
    weight_pct: Percent


class UnpricedPositionRead(BaseModel):
    symbol: str
    exchange: Exchange
    quantity: int
    reason: str | None


class ConcentrationRead(BaseModel):
    """How much of the portfolio sits in its largest positions.

    ``hhi`` is the Herfindahl-Hirschman Index on the 0-10,000 scale: the sum of squared
    percentage weights. ``effective_holdings`` is its reciprocal form - the number of
    equally-sized positions the portfolio behaves like.
    """

    holdings_counted: int
    top_holding: WeightRead | None
    top_1_pct: Percent | None
    top_3_pct: Percent | None
    top_5_pct: Percent | None
    hhi: Percent | None
    hhi_band: str | None
    effective_holdings: Percent | None


class SectorAllocationRead(BaseModel):
    available: bool
    note: str
    weights: list[WeightRead] = []


class AllocationRead(BaseModel):
    portfolio_id: uuid.UUID
    portfolio_name: str
    currency: Literal["INR"] = "INR"
    as_of: datetime
    data_as_of: date | None
    priced_market_value: Money | None
    holdings: list[WeightRead]
    concentration: ConcentrationRead
    sectors: SectorAllocationRead
    unpriced_positions: list[UnpricedPositionRead]
    note: str


# --- Ledger views: P&L, timeline and attribution (M4.3) -----------------------------------


class SecurityPnlRead(BaseModel):
    symbol: str
    exchange: Exchange
    quantity: int
    cost_basis: Money | None  # cost of the shares still held, fees included
    average_cost: Money | None
    market_value: Money | None
    realised_pnl: Money
    unrealised_pnl: Money | None
    total_pnl: Money | None
    contributions: Money
    withdrawals: Money
    fees: Money
    price_date: date | None
    price_note: str | None = None


class PnlTotalsRead(BaseModel):
    realised_pnl: Money
    unrealised_pnl: Money | None
    total_pnl: Money | None
    contributions: Money
    withdrawals: Money
    net_invested: Money
    fees: Money
    open_cost_basis: Money
    market_value: Money | None
    is_complete: bool  # false when any open position could not be priced


class PnlMethodologyRead(BaseModel):
    cost_basis: Literal["FIFO"] = "FIFO"
    note: str
    basis: HistoryBasis
    available: bool = True


class PortfolioPnlRead(BaseModel):
    portfolio_id: uuid.UUID
    portfolio_name: str
    currency: Literal["INR"] = "INR"
    as_of: datetime
    data_as_of: date | None
    totals: PnlTotalsRead | None
    securities: list[SecurityPnlRead]
    unmatched_sales: list[str] = []
    methodology: PnlMethodologyRead


class TimelineTransactionRead(BaseModel):
    kind: Literal["BUY", "SELL"]
    symbol: str
    exchange: Exchange
    quantity: int
    price: Money
    fees: Money
    gross_value: Money
    cash_flow: Money
    reference: str | None = None
    trade_date: date  # as entered, which may differ from the session it is recognised on


class TimelineEntryRead(BaseModel):
    """One session on which something happened, with its effect on the portfolio."""

    trade_date: date
    transactions: list[TimelineTransactionRead]
    position_changes: list[str]  # e.g. "TCS +10 -> 30"
    portfolio_value: Money | None
    net_cash_flow: Money
    daily_return_pct: Percent | None
    cumulative_return_pct: Percent | None


class PortfolioTimelineRead(BaseModel):
    portfolio_id: uuid.UUID
    portfolio_name: str
    currency: Literal["INR"] = "INR"
    as_of: datetime
    basis: HistoryBasis
    entries: list[TimelineEntryRead]
    transaction_count: int
    note: str


class ContributionRead(BaseModel):
    symbol: str
    exchange: Exchange
    contribution_pct: Percent
    start_value: Money | None
    end_value: Money | None
    start_weight_pct: Percent | None
    end_weight_pct: Percent | None
    sessions_counted: int


class DailyContributionRead(BaseModel):
    symbol: str
    exchange: Exchange
    contribution_pct: Percent
    value_change: Money
    cash_flow: Money


class AttributionRead(BaseModel):
    """Which securities moved the portfolio, and by how much.

    ``sum_of_daily_returns_pct`` is what the contributions add up to. It is deliberately not
    the same number as the chained time-weighted return: compounding separates them, and both
    are shown rather than one being passed off as the other.
    """

    portfolio_id: uuid.UUID
    portfolio_name: str
    currency: Literal["INR"] = "INR"
    as_of: datetime
    basis: HistoryBasis
    period: PeriodRead
    sessions_counted: int
    twr_pct: Percent | None
    sum_of_daily_returns_pct: Percent | None
    compounding_difference_pct: Percent | None
    contributors: list[ContributionRead]
    detractors: list[ContributionRead]
    latest_session: date | None
    latest_contributions: list[DailyContributionRead]
    benchmark: BenchmarkRead | None = None
    benchmark_gap_pct: Percent | None = None
    stale_positions: list[str] = []
    note: str


# --- Deterministic portfolio intelligence (M5) --------------------------------------------
#
# Every field here is a rendering of a number computed elsewhere in this package. Nothing in
# this layer estimates, predicts, ranks by judgement, or describes a security as good or bad:
# it states measured facts and says plainly when a fact is unavailable.


class IntelligenceStatus(StrEnum):
    AVAILABLE = "available"  # enough data to explain the window
    LIMITED = "limited"  # explained, but coverage or staleness qualifies it
    UNAVAILABLE = "unavailable"  # nothing measurable


class ContributorRead(BaseModel):
    """One security's share of the portfolio's return over the window."""

    rank: int
    symbol: str
    exchange: Exchange
    contribution_pct: Percent  # percentage points of portfolio return
    security_return_pct: Percent | None  # the security's own return over the window
    start_value: Money | None
    end_value: Money | None
    net_flow: Money
    start_weight_pct: Percent | None
    end_weight_pct: Percent | None
    sessions_counted: int


class ReturnExplanationRead(BaseModel):
    portfolio_return_pct: Percent | None
    benchmark_return_pct: Percent | None
    relative_return_pct: Percent | None
    calculation_method: CalculationMethod
    basis: HistoryBasis
    sum_of_contributions_pct: Percent | None
    compounding_difference_pct: Percent | None
    contributions_reconcile: bool  # the parts add up to the measured sum, exactly
    top_positive: list[ContributorRead]
    top_negative: list[ContributorRead]
    latest_session: date | None
    latest_session_movers: list[ContributorRead]
    note: str


class CashFlowExplanationRead(BaseModel):
    """Why a change in portfolio value is not the same thing as a return."""

    start_value: Money | None
    end_value: Money | None
    value_change: Money | None
    contributions: Money | None
    withdrawals: Money | None
    net_external_flow: Money | None
    return_driven_change: Money | None  # value change less the net flow
    flow_share_of_change_pct: Percent | None
    twr_pct: Percent | None
    available: bool
    note: str


class RiskExplanationRead(BaseModel):
    volatility_pct: Percent | None
    downside_volatility_pct: Percent | None
    max_drawdown_pct: Percent | None
    current_drawdown_pct: Percent | None
    positive_sessions: int
    negative_sessions: int
    flat_sessions: int
    beta: Percent | None
    largest_position_symbol: str | None
    largest_position_weight_pct: Percent | None
    top_3_weight_pct: Percent | None
    hhi: Percent | None
    concentration_band: str | None
    effective_holdings: Percent | None
    note: str


class DataQualityRead(BaseModel):
    """What the numbers above can and cannot be held to."""

    status: IntelligenceStatus
    coverage_status: CoverageStatus
    sessions_available: int
    sessions_expected: int
    sessions_behind_latest: int
    latest_expected_session: date | None
    missing_session_count: int
    stale_securities: list[str]
    excluded_securities: list[str]
    benchmark_status: str
    benchmark_basis: str | None
    reconciliation_status: ReconciliationStatus
    price_anomalies: PriceAnomaliesRead | None = None
    limitations: list[str]
    note: str


class PortfolioIntelligenceRead(BaseModel):
    """A deterministic explanation of what the portfolio's numbers say.

    This is a composition of measurements already published by the performance, attribution,
    P&L and allocation endpoints - not a second opinion about them. It contains no forecasts,
    no recommendations and no free-form narrative.
    """

    portfolio_id: uuid.UUID
    portfolio_name: str
    currency: Literal["INR"] = "INR"
    as_of: datetime
    status: IntelligenceStatus
    period: PeriodRead
    headline: str
    findings: list[str]
    returns: ReturnExplanationRead | None
    money_weighted: MoneyWeightedRead | None
    cash_flow: CashFlowExplanationRead | None
    risk: RiskExplanationRead | None
    data_quality: DataQualityRead
    # Present only when explicitly requested: every headline figure with its provenance.
    trace: list["TraceEntryRead"] | None = None
    methodology: str


class TraceEntryRead(BaseModel):
    """Where one published figure came from.

    An audit aid, not a UI feature: it answers "which calculation produced this, from what, by
    what formula" without the reader having to read the source. Returned only when the caller
    asks for it, so the ordinary response stays the size it was.
    """

    metric: str
    value: str | None
    source: str  # the module and function that produced it
    inputs: dict[str, str]  # the figures it was computed from
    formula: str
