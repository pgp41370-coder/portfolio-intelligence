"""Detect price moves large enough to invalidate the figures built on them.

A split, a bonus issue or a consolidation changes the number of shares and the price together.
The provider reports the price; nobody reports the share change to this application. So a 1-for-2
split arrives as a 50% overnight fall, and every number computed from that series - the daily
return, the contribution, the drawdown, the cost basis, the time- and money-weighted returns -
silently becomes wrong for that security.

The valuation card already warns when the **latest** two closes move like this. Nothing looked at
the rest of the window, which is what every analytic is actually built from. This module does.

A move is flagged when it is larger than the project's generic large-move threshold, **or** when
it lands within a whisker of a ratio a corporate action would produce and is at least
``RATIO_MIN_MOVE``. The second rule matters: a 1:2 bonus issue moves the price by a third, which
the generic threshold alone would never catch.

**It detects and discloses; it never adjusts.** Correcting a split needs the ratio and the
effective date from a corporate-action feed, which this application does not have. Inventing the
adjustment would silently rewrite the user's history, which is worse than saying plainly that a
figure may be wrong and why.

The ``consistent_with`` field is arithmetic, not a claim: a fall of almost exactly one half is
what a 1-for-2 split produces, and saying so helps a reader tell a corporate action from a crash.
It is offered only when the move lands within ``RATIO_TOLERANCE`` of a common ratio, and the
response says in words that it is unconfirmed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from enum import StrEnum

from app.performance.positions import SecurityKey
from app.valuation.service import LARGE_PRICE_MOVE_THRESHOLD

_CONTEXT = Context(prec=34, rounding=ROUND_HALF_UP)

# The project's existing threshold for "this is probably not a price move", shared with the
# valuation card so the two cannot drift apart.
DEFAULT_THRESHOLD = LARGE_PRICE_MOVE_THRESHOLD
RATIO_TOLERANCE = Decimal("0.02")  # within 2% of the ratio a corporate action would produce
# A move that lands almost exactly on a corporate-action ratio is suspicious at a lower bar than
# an arbitrary one: a 1:2 bonus issue moves the price by a third, which the generic threshold
# would miss entirely. Below this, ordinary volatility would match a ratio by coincidence.
RATIO_MIN_MOVE = Decimal("0.20")
MAX_REPORTED = 20

# What the close is multiplied by, and the action that produces it. Splits and bonus issues cut
# the price; consolidations raise it.
_RATIOS: tuple[tuple[Decimal, str], ...] = (
    (Decimal("0.5"), "a 1-for-2 split, or a 1:1 bonus issue"),
    (Decimal(1) / Decimal(3), "a 1-for-3 split, or a 2:1 bonus issue"),
    (Decimal("0.25"), "a 1-for-4 split, or a 3:1 bonus issue"),
    (Decimal("0.2"), "a 1-for-5 split"),
    (Decimal("0.1"), "a 1-for-10 split"),
    (Decimal(2) / Decimal(3), "a 1:2 bonus issue"),
    (Decimal("0.75"), "a 1:3 bonus issue"),
    (Decimal(2), "a 2-for-1 consolidation"),
    (Decimal(5), "a 5-for-1 consolidation"),
    (Decimal(10), "a 10-for-1 consolidation"),
)


class AnomalyTrigger(StrEnum):
    """Why this move was flagged."""

    LARGE_MOVE = "large_move"  # bigger than the generic threshold
    CORPORATE_ACTION_RATIO = "corporate_action_ratio"  # lands on a ratio an action would produce


@dataclass(frozen=True, slots=True)
class PriceAnomaly:
    """One session-over-session move large enough to distrust."""

    key: SecurityKey
    previous_date: date
    trade_date: date
    previous_close: Decimal
    close: Decimal
    change: Decimal  # as a fraction
    consistent_with: str | None
    trigger: AnomalyTrigger

    @property
    def symbol(self) -> str:
        return self.key[0]

    @property
    def exchange(self) -> str:
        return self.key[1]


def detect_anomalies(
    closes: dict[SecurityKey, dict[date, Decimal]],
    *,
    window: Sequence[date] | None = None,
    threshold: Decimal = DEFAULT_THRESHOLD,
) -> list[PriceAnomaly]:
    """Every move of at least ``threshold`` between consecutive stored closes.

    Consecutive *stored* closes, not calendar days: a gap in the data is already reported as a
    gap, and a move measured across one is still a move worth flagging. Both dates are carried
    so a reader can see how far apart they are.
    """
    first, last = (window[0], window[-1]) if window else (None, None)
    found: list[PriceAnomaly] = []

    with localcontext(_CONTEXT):
        for key in sorted(closes):
            series = closes[key]
            days = sorted(day for day in series if (first is None or first <= day <= last))
            for index in range(1, len(days)):
                previous_close = series[days[index - 1]]
                close = series[days[index]]
                if previous_close <= 0:
                    continue
                change = close / previous_close - 1
                size = abs(change)
                # Almost every session is an ordinary move. Testing it against ten ratios first
                # would be ten divisions wasted on each one, so the cheap check comes first.
                if size < RATIO_MIN_MOVE:
                    continue
                ratio = _matching_ratio(close / previous_close)
                if size >= threshold:
                    trigger = AnomalyTrigger.LARGE_MOVE
                elif ratio is not None:
                    trigger = AnomalyTrigger.CORPORATE_ACTION_RATIO
                else:
                    continue
                found.append(
                    PriceAnomaly(
                        key=key,
                        previous_date=days[index - 1],
                        trade_date=days[index],
                        previous_close=previous_close,
                        close=close,
                        change=change,
                        consistent_with=ratio,
                        trigger=trigger,
                    )
                )
    # Largest move first: the most likely to matter, and a stable order for equal moves.
    found.sort(key=lambda item: (-abs(item.change), item.key, item.trade_date))
    return found


def _matching_ratio(multiplier: Decimal) -> str | None:
    """The corporate action that would produce this exact ratio, when one nearly does."""
    with localcontext(_CONTEXT):
        for ratio, description in _RATIOS:
            if abs(multiplier - ratio) / ratio <= RATIO_TOLERANCE:
                return description
    return None


def describe(anomaly: PriceAnomaly) -> str:
    """One factual sentence: what moved, when, by how much, and what it may mean."""
    direction = "fell" if anomaly.change < 0 else "rose"
    with localcontext(_CONTEXT):
        percent = (abs(anomaly.change) * Decimal(100)).quantize(Decimal("0.01"))
    sentence = (
        f"{anomaly.symbol} {direction} {percent}% between {anomaly.previous_date:%d %b %Y} and "
        f"{anomaly.trade_date:%d %b %Y}."
    )
    if anomaly.consistent_with:
        sentence += f" A move of that size is what {anomaly.consistent_with} would produce."
    return sentence


def consequence_note(count: int) -> str:
    """What a reader should take from the flags, stated once rather than per row."""
    subject = "One price move" if count == 1 else f"{count} price moves"
    return (
        f"{subject} in this window {'is' if count == 1 else 'are'} large enough to distrust. "
        "The application has no corporate-action data, so it cannot tell a split, bonus issue or "
        "consolidation from a genuine price move, and it does not adjust for either. Where one of "
        "these is a corporate action, the return, contribution, drawdown and cost-basis figures "
        "for that security are wrong, and the quantities on record are wrong too."
    )
