"""Deterministic calculations derived only from user-provided portfolio data.

No market prices are involved, so nothing here is a market value, return or profit.
"""

from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol

_FOUR_PLACES = Decimal("0.0001")


class Position(Protocol):
    @property
    def quantity(self) -> int: ...

    @property
    def average_buy_price(self) -> Decimal: ...


def total_invested_capital(positions: Iterable[Position]) -> Decimal:
    """SUM(quantity × average_buy_price), computed exactly with Decimal arithmetic."""
    return sum(
        (Decimal(position.quantity) * position.average_buy_price for position in positions),
        Decimal("0"),
    )


def format_amount(value: Decimal) -> str:
    """Plain decimal string with 2 to 4 decimal places, e.g. '1650.00' or '1650.3333'."""
    whole, _, fraction = f"{value.quantize(_FOUR_PLACES):f}".partition(".")
    return f"{whole}.{fraction.rstrip('0').ljust(2, '0')}"
