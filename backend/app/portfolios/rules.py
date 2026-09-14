"""Validation rules for portfolio input, shared by the JSON API and CSV import.

Each function raises ValueError with a message that is safe to show to the user.
Symbols are checked for format only; whether a symbol is actually listed on
NSE or BSE requires a security master and is not verified yet.
"""

import re
from decimal import Decimal
from enum import StrEnum

MAX_PORTFOLIO_NAME_LENGTH = 100
MAX_SYMBOL_LENGTH = 20
MAX_HOLDINGS_PER_PORTFOLIO = 500
MAX_QUANTITY = 1_000_000_000
PRICE_DECIMAL_PLACES = 4
MAX_AVERAGE_BUY_PRICE = Decimal("9999999999.9999")  # fits NUMERIC(14, 4)

_PRICE_QUANTUM = Decimal(1).scaleb(-PRICE_DECIMAL_PLACES)
# Letters, digits, '&' and '-': covers symbols such as M&M, BAJAJ-AUTO and BSE scrip codes like 500180.
SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9&-]*")
_NUMBER_PATTERN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


def normalize_portfolio_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Portfolio name must be text.")
    name = " ".join(value.split())
    if not name:
        raise ValueError("Portfolio name is required.")
    if len(name) > MAX_PORTFOLIO_NAME_LENGTH:
        raise ValueError(f"Portfolio name must be at most {MAX_PORTFOLIO_NAME_LENGTH} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("Portfolio name contains invalid characters.")
    return name


def normalize_symbol(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Symbol must be text.")
    symbol = value.strip().upper()
    if not symbol:
        raise ValueError("Symbol is required.")
    if len(symbol) > MAX_SYMBOL_LENGTH:
        raise ValueError(f"Symbol must be at most {MAX_SYMBOL_LENGTH} characters.")
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError(
            "Symbol must start with a letter or digit and contain only letters, digits, '&' or '-'."
        )
    return symbol


def normalize_exchange(value: object) -> Exchange:
    if isinstance(value, Exchange):
        return value
    if not isinstance(value, str):
        raise ValueError("Exchange must be NSE or BSE.")
    code = value.strip().upper()
    if not code:
        raise ValueError("Exchange is required.")
    try:
        return Exchange(code)
    except ValueError:
        raise ValueError("Exchange must be NSE or BSE.") from None


def parse_quantity(value: object) -> int:
    number = _to_decimal(value, "Quantity")
    if number <= 0:
        raise ValueError("Quantity must be greater than 0.")
    if number != number.to_integral_value():
        raise ValueError("Quantity must be a whole number of shares.")
    if number > MAX_QUANTITY:
        raise ValueError(f"Quantity must be at most {MAX_QUANTITY:,}.")
    return int(number)


def parse_average_buy_price(value: object) -> Decimal:
    number = _to_decimal(value, "Average buy price")
    if number <= 0:
        raise ValueError("Average buy price must be greater than 0.")
    if number > MAX_AVERAGE_BUY_PRICE:
        raise ValueError(f"Average buy price must be at most {MAX_AVERAGE_BUY_PRICE:,}.")
    exponent = number.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -PRICE_DECIMAL_PLACES:
        raise ValueError(f"Average buy price can have at most {PRICE_DECIMAL_PLACES} decimal places.")
    return number.quantize(_PRICE_QUANTUM)


def _to_decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number.")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{label} is required.")
        if not _NUMBER_PATTERN.fullmatch(text):
            raise ValueError(
                f"{label} must be a number using digits and an optional decimal point "
                "(no commas or currency symbols)."
            )
        number = Decimal(text)
    else:
        raise ValueError(f"{label} must be a number.")
    if not number.is_finite():
        raise ValueError(f"{label} must be a finite number.")
    return number
