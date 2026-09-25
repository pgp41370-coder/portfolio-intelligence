"""Validation rules for transaction input.

Each function raises ValueError with a message that is safe to show to the user, matching the
convention in app/portfolios/rules.py. Rules that need the trading calendar or the current
time (future-dated trades, oversells) live in the service layer, which has both.
"""

from datetime import date
from decimal import Decimal

from app.portfolios.rules import PRICE_DECIMAL_PLACES, parse_decimal, parse_quantity  # noqa: F401

MAX_TRANSACTIONS_PER_PORTFOLIO = 5_000
MAX_PRICE = Decimal("9999999999.9999")  # fits NUMERIC(14, 4)
MAX_FEES = Decimal("9999999999.9999")
MAX_REFERENCE_LENGTH = 64
# Nothing in this application has price history before this; a date below it is a typo.
EARLIEST_TRADE_DATE = date(1994, 11, 3)  # NSE equities segment began trading

_PRICE_QUANTUM = Decimal(1).scaleb(-PRICE_DECIMAL_PLACES)
KINDS = ("BUY", "SELL")


def normalize_kind(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Transaction type must be BUY or SELL.")
    kind = value.strip().upper()
    if kind not in KINDS:
        raise ValueError("Transaction type must be BUY or SELL.")
    return kind


def parse_price(value: object, label: str = "Price") -> Decimal:
    number = parse_decimal(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    if number > MAX_PRICE:
        raise ValueError(f"{label} must be at most {MAX_PRICE:,}.")
    return _quantize(number, label)


def parse_fees(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    number = parse_decimal(value, "Fees")
    if number < 0:
        raise ValueError("Fees cannot be negative.")
    if number > MAX_FEES:
        raise ValueError(f"Fees must be at most {MAX_FEES:,}.")
    return _quantize(number, "Fees")


def parse_trade_date(value: object) -> date:
    if isinstance(value, date):
        day = value
    elif isinstance(value, str):
        try:
            day = date.fromisoformat(value.strip())
        except ValueError:
            raise ValueError("Trade date must be a date in YYYY-MM-DD format.") from None
    else:
        raise ValueError("Trade date must be a date in YYYY-MM-DD format.")
    if day < EARLIEST_TRADE_DATE:
        raise ValueError(f"Trade date must be on or after {EARLIEST_TRADE_DATE:%d %b %Y}.")
    return day


def normalize_reference(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Reference must be text.")
    reference = " ".join(value.split())
    if not reference:
        return None
    if len(reference) > MAX_REFERENCE_LENGTH:
        raise ValueError(f"Reference must be at most {MAX_REFERENCE_LENGTH} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in reference):
        raise ValueError("Reference contains invalid characters.")
    return reference


def _quantize(number: Decimal, label: str) -> Decimal:
    exponent = number.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -PRICE_DECIMAL_PLACES:
        raise ValueError(f"{label} can have at most {PRICE_DECIMAL_PLACES} decimal places.")
    return number.quantize(_PRICE_QUANTUM)
