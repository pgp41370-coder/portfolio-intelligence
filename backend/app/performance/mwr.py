"""Money-weighted return (XIRR): the rate the investor's own cash flows earned.

This answers a different question from the time-weighted return, and neither answer supersedes
the other:

* **TWR** measures the portfolio, with the effect of deposits and withdrawals removed. It is
  what you compare against a benchmark.
* **MWR** measures the investor, including when and how much money was put in or taken out.
  Two people holding the same fund over the same year have the same TWR and different MWRs.

Method: solve ``Sum CF_i x (1 + r)^(-d_i / 365) = 0``, where ``d_i`` is the actual number of
days from the first cash flow. Actual/365, and **bisection** rather than Newton-Raphson:
bisection cannot diverge, needs no derivative, and converges in a fixed number of steps, which
keeps the result deterministic.

The equation is solved for the **period** rate ``g`` - the return over the window itself - using
the equivalent exponent ``d_i / D`` where ``D`` is the window's length in days. The annualised
rate follows from ``1 + r = (1 + g)^(365/D)``. The two forms have the same roots, but solving in
period terms keeps the search well behaved: a 21% gain over two days is an ordinary period
return and an absurd annual one, and searching for the latter would find nothing inside any
sane range.

The rate is found in two stages. The plausible range is first **scanned in floating point** to
locate every interval where the present value crosses zero - a search, not a measurement, and
400x cheaper than the same scan in ``Decimal`` (85 ms against 0.2 ms, measured). Each bracket
is then confirmed and bisected in ``Decimal``, so every published figure comes from exact
decimal arithmetic at the project's usual precision. A bracket the float scan proposes but
``Decimal`` does not confirm is discarded.

Sign convention, from the investor's side: **money paid into the portfolio is negative**, money
received is positive, and the terminal value is positive because it is what holding the
portfolio is worth at the end. The ledger's own flows are portfolio-inward positive, so the
builder below negates them exactly once.

Two rules protect the reader from a number that looks precise and is not:

1. **Multiple roots are withheld, never resolved by preference.** A cash-flow series with
   several sign changes can satisfy the equation at several rates. Picking one - the smallest,
   the nearest zero, the "sensible looking" one - would be a judgement the data does not
   support, so the status says ``ambiguous_multiple_roots`` and no figure is published.
2. **Annualising a short window is withheld.** Over a fortnight, a 2% gain annualises to
   something absurd. Below ``MIN_DAYS_FOR_ANNUALISATION`` only the period figure is published,
   with the reason attached.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from enum import StrEnum

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)

DAYS_PER_YEAR = Decimal(365)
# A rate below -100% is meaningless, and (1 + r) must stay positive for the power to exist.
MIN_RATE = Decimal("-0.9999")
MAX_RATE = Decimal(100)  # +10,000% over the window; beyond this the answer is not a number anyone needs
# Search resolution. Fine where real portfolio returns live, coarse in the tail; the float
# scan makes this affordable, and a finer grid is what makes a second root visible.
SCAN_STEP = 0.005
FINE_SCAN_LIMIT = 2.0
COARSE_SCAN_STEP = 0.05
TOLERANCE = Decimal("0.0000000001")  # bisection stops when the bracket is this narrow
MAX_ITERATIONS = 200
MIN_DAYS_FOR_ANNUALISATION = 90


class MoneyWeightedStatus(StrEnum):
    """Why a money-weighted return is, or is not, being published."""

    AVAILABLE = "available"
    NOT_APPLICABLE = "not_applicable"  # no transaction ledger, so no investor cash flows
    INSUFFICIENT_HISTORY = "insufficient_history"  # nothing invested, or a single dated flow
    NO_SOLUTION = "no_solution"  # no rate satisfies the equation within the searched range
    AMBIGUOUS_MULTIPLE_ROOTS = "ambiguous_multiple_roots"  # several rates satisfy it


@dataclass(frozen=True, slots=True)
class CashFlow:
    """One dated movement, from the investor's point of view."""

    on: date
    amount: Decimal  # negative: paid in.  positive: received, including the terminal value


@dataclass(frozen=True, slots=True)
class MoneyWeightedResult:
    status: MoneyWeightedStatus
    annualised: Decimal | None  # the XIRR itself, as a fraction
    period: Decimal | None  # (1 + annualised)^(days/365) - 1, comparable with a cumulative TWR
    days: int
    roots_found: int
    contributions: Decimal
    withdrawals: Decimal
    terminal_value: Decimal | None
    note: str
    annualisation_note: str | None = None

    @property
    def available(self) -> bool:
        return self.status is MoneyWeightedStatus.AVAILABLE


def build_cash_flows(
    sessions: Sequence[date],
    flows: Sequence[Decimal],
    terminal_value: Decimal,
    *,
    opening_value: Decimal = Decimal(0),
) -> list[CashFlow]:
    """Turn a valued window into the investor's cash flows.

    ``opening_value`` is what the position carried in from before the window was worth at the
    first session's close. It is zero when the window covers the whole ledger, and then the
    first session's own flow - the actual cost, fees included - is the initial investment. For
    a window that starts mid-history the opening position is the capital at stake, valued at
    market, and the fees paid to acquire it fall outside the window.

    The terminal value is added to the final session: holding the portfolio at the end is worth
    the same to the investor as selling it would be.
    """
    if not sessions:
        return []
    with localcontext(_CONTEXT):
        entries = [
            CashFlow(on=day, amount=-flow)
            for day, flow in zip(sessions, flows, strict=True)
            if flow != 0
        ]
        if opening_value:
            entries.append(CashFlow(on=sessions[0], amount=-opening_value))
        entries.append(CashFlow(on=sessions[-1], amount=terminal_value))
    return sorted(entries, key=lambda item: item.on)


def money_weighted_return(flows: Sequence[CashFlow]) -> MoneyWeightedResult:
    """Solve for the annualised rate, and report why when it cannot be solved."""
    with localcontext(_CONTEXT):
        contributions = sum((-item.amount for item in flows if item.amount < 0), Decimal(0))
        withdrawals = sum((item.amount for item in flows if item.amount > 0), Decimal(0))
        terminal = flows[-1].amount if flows else None
        days = (flows[-1].on - flows[0].on).days if len(flows) > 1 else 0

        def result(
            status: MoneyWeightedStatus,
            note: str,
            *,
            annualised: Decimal | None = None,
            period: Decimal | None = None,
            roots: int = 0,
            annualisation_note: str | None = None,
        ) -> MoneyWeightedResult:
            return MoneyWeightedResult(
                status=status,
                annualised=annualised,
                period=period,
                days=days,
                roots_found=roots,
                contributions=contributions,
                withdrawals=withdrawals,
                terminal_value=terminal,
                note=note,
                annualisation_note=annualisation_note,
            )

        if len(flows) < 2:
            return result(
                MoneyWeightedStatus.INSUFFICIENT_HISTORY,
                "A money-weighted return needs at least two dated cash flows.",
            )
        if contributions == 0:
            return result(
                MoneyWeightedStatus.INSUFFICIENT_HISTORY,
                "No money was paid into this portfolio over the window, so there is no invested "
                "capital to measure a return on.",
            )
        if days <= 0:
            return result(
                MoneyWeightedStatus.INSUFFICIENT_HISTORY,
                "Every cash flow falls on the same day, so no rate of return can be measured.",
            )

        roots = _find_roots(flows, days)
        if not roots:
            return result(
                MoneyWeightedStatus.NO_SOLUTION,
                f"No rate between {MIN_RATE:%} and {MAX_RATE:%} satisfies the cash flows. This "
                "usually means the flows never change sign.",
            )
        if len(roots) > 1:
            return result(
                MoneyWeightedStatus.AMBIGUOUS_MULTIPLE_ROOTS,
                f"{len(roots)} different rates satisfy these cash flows, so no single "
                "money-weighted return can be stated. Choosing one of them would be a "
                "judgement the data does not support.",
                roots=len(roots),
            )

        period = _normalise_zero(roots[0])
        annualised = _annualised_return(period, days)
        if days < MIN_DAYS_FOR_ANNUALISATION:
            return result(
                MoneyWeightedStatus.AVAILABLE,
                "Measured from the investor's own cash flows.",
                period=period,
                roots=1,
                annualisation_note=(
                    f"Annualised figure withheld: the window is {days} days, and annualising "
                    f"fewer than {MIN_DAYS_FOR_ANNUALISATION} projects a short run onto a whole "
                    "year. The period figure above covers exactly the window measured."
                ),
            )
        return result(
            MoneyWeightedStatus.AVAILABLE,
            "Measured from the investor's own cash flows.",
            annualised=annualised,
            period=period,
            roots=1,
        )


def net_present_value(flows: Sequence[CashFlow], rate: Decimal) -> Decimal:
    """Sum of the flows discounted at an annual ``rate``, actual/365 from the first flow.

    The public definition of the equation being solved. The solver works in period terms,
    which is the same equation reparameterised.
    """
    start = flows[0].on
    with localcontext(_CONTEXT):
        total = Decimal(0)
        for item in flows:
            years = Decimal((item.on - start).days) / DAYS_PER_YEAR
            total += item.amount / (Decimal(1) + rate) ** years
        return total


def _period_npv(flows: Sequence[CashFlow], rate: Decimal, days: int) -> Decimal:
    """The same sum, discounted at a rate covering the whole window rather than a year."""
    start = flows[0].on
    span = Decimal(days)
    with localcontext(_CONTEXT):
        total = Decimal(0)
        for item in flows:
            fraction = Decimal((item.on - start).days) / span
            total += item.amount / (Decimal(1) + rate) ** fraction
        return total


def _find_roots(flows: Sequence[CashFlow], days: int) -> list[Decimal]:
    """Every rate in the searched range at which the present value crosses zero.

    Scanning rather than starting from a guess is what makes a second root visible instead of
    invisible. The scan is float; each bracket it proposes is confirmed and solved in Decimal.
    """
    start = flows[0].on
    float_pairs = [(float((item.on - start).days) / float(days), float(item.amount)) for item in flows]

    def npv_float(rate: float) -> float | None:
        base = 1.0 + rate
        if base <= 0:
            return None
        try:
            return sum(amount / base**years for years, amount in float_pairs)
        except (OverflowError, ZeroDivisionError):
            return None

    roots: list[Decimal] = []
    previous_rate, previous = float(MIN_RATE), npv_float(float(MIN_RATE))
    for rate in _scan_rates():
        current = npv_float(rate)
        if current is None or previous is None:
            previous_rate, previous = rate, current
            continue
        crosses = current == 0.0 or (previous < 0) != (current < 0)
        if crosses:
            root = _confirm_and_solve(flows, Decimal(str(previous_rate)), Decimal(str(rate)), days)
            if root is not None:
                roots.append(root)
        previous_rate, previous = rate, current
    return roots


def _confirm_and_solve(
    flows: Sequence[CashFlow], low: Decimal, high: Decimal, days: int
) -> Decimal | None:
    """Check in Decimal that the bracket really contains a crossing, then bisect it."""
    low_value, high_value = _safe_npv(flows, low, days), _safe_npv(flows, high, days)
    if low_value is None or high_value is None:
        return None
    if low_value == 0:
        return low
    if high_value == 0:
        return high
    if (low_value < 0) == (high_value < 0):
        return None  # the float scan proposed it; Decimal does not agree
    return _bisect(flows, low, high, days)


def _scan_rates() -> list[float]:
    """The grid of candidate rates: fine where real answers live, coarser further out."""
    rates: list[float] = []
    rate = float(MIN_RATE) + SCAN_STEP
    while rate <= FINE_SCAN_LIMIT:
        rates.append(round(rate, 6))
        rate += SCAN_STEP
    rate = FINE_SCAN_LIMIT + COARSE_SCAN_STEP
    while rate <= float(MAX_RATE):
        rates.append(round(rate, 6))
        rate += COARSE_SCAN_STEP
    return rates


def _bisect(flows: Sequence[CashFlow], low: Decimal, high: Decimal, days: int) -> Decimal:
    """Halve a bracket that contains a sign change until it is narrower than the tolerance."""
    low_value = _safe_npv(flows, low, days)
    for _ in range(MAX_ITERATIONS):
        if high - low < TOLERANCE:
            break
        middle = (low + high) / 2
        middle_value = _safe_npv(flows, middle, days)
        if middle_value is None or middle_value == 0:
            return middle
        if (low_value < 0) != (middle_value < 0):
            high = middle
        else:
            low, low_value = middle, middle_value
    return (low + high) / 2


def _safe_npv(flows: Sequence[CashFlow], rate: Decimal, days: int) -> Decimal | None:
    """Present value, or None where the power is undefined rather than merely extreme."""
    try:
        return _period_npv(flows, rate, days)
    except (InvalidOperation, ZeroDivisionError, OverflowError):
        return None


def _annualised_return(period: Decimal, days: int) -> Decimal | None:
    """The window's rate restated as an annual one: 1 + r = (1 + g)^(365/days)."""
    if days <= 0 or period <= -1:
        return None
    with localcontext(_CONTEXT):
        try:
            return _normalise_zero((Decimal(1) + period) ** (DAYS_PER_YEAR / Decimal(days)) - 1)
        except (InvalidOperation, OverflowError):
            return None


def _normalise_zero(value: Decimal) -> Decimal:
    """Collapse a result the solver cannot distinguish from zero to exactly zero.

    Bisection stops once the bracket is narrower than ``TOLERANCE``, so a true zero can come
    back as a tiny negative number - which would then print as "-0.00%", implying a loss that
    was not measured.
    """
    return Decimal(0) if abs(value) < TOLERANCE else value
