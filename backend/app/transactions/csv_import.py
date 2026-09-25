"""Parse and validate a transactions CSV.

Accepted format (header required, column order free, names case-insensitive). ``fees`` and
``reference`` are optional columns:

    trade_date,symbol,exchange,type,quantity,price,fees,reference
    2026-03-02,RELIANCE,NSE,BUY,10,1234.50,23.60,ORD-1

Parsing uses Python's standard csv module on decoded text only: cell values are treated as plain
strings, no formulas are evaluated, nothing is executed and nothing is written to disk. A cell
beginning with ``=``, ``+`` or ``@`` is therefore harmless on the way in - it simply fails the
symbol or number rules, or is stored verbatim in ``reference``. **If a CSV export is ever added,
it must neutralise those values on the way out** (the usual prefix with an apostrophe), because
that is where a spreadsheet would evaluate them; rejecting them here instead would throw away
legitimate references without protecting anything.

**The whole file is validated before anything is imported.** Every row is checked, so the user
sees every problem at once rather than fixing them one upload at a time, and an import either
applies in full or not at all. That matters more here than for holdings: a half-imported ledger
produces a wrong cost basis and a wrong return, silently.

Validation runs the ledger forward as it goes, so a sale is judged against the position the
earlier rows actually produce - including transactions already stored for that portfolio.
"""

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TypeVar

from app.portfolios.rules import Exchange, normalize_exchange, normalize_symbol
from app.transactions.rules import (
    MAX_TRANSACTIONS_PER_PORTFOLIO,
    normalize_kind,
    normalize_reference,
    parse_fees,
    parse_price,
    parse_quantity,
    parse_trade_date,
)
from app.transactions.schemas import TransactionInput

REQUIRED_COLUMNS = ("trade_date", "symbol", "exchange", "type", "quantity", "price")
OPTIONAL_COLUMNS = ("fees", "reference")
CSV_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_SIZE_LABEL = "1 MB"
ALLOWED_CSV_CONTENT_TYPES = frozenset(
    {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream", ""}
)

_EXPECTED_HEADER = ",".join(REQUIRED_COLUMNS)
T = TypeVar("T")


@dataclass(frozen=True)
class CsvIssue:
    message: str
    row: int | None = None
    column: str | None = None


@dataclass
class TransactionCsvResult:
    transactions: list[TransactionInput] = field(default_factory=list)
    errors: list[CsvIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def parse_transactions_csv(
    content: bytes,
    *,
    latest_session: date,
    existing: list[tuple[date, str, str, str, int]] | None = None,
    existing_count: int = 0,
) -> TransactionCsvResult:
    """Validate every row. Row numbers count the header as row 1, as in a spreadsheet.

    ``existing`` is the portfolio's stored ledger as ``(trade_date, symbol, exchange, kind,
    quantity)`` tuples: it seeds the running position so a sale in the file is checked against
    what is really held, and it is what duplicate detection compares against.
    """
    result = TransactionCsvResult()

    text = _decode(content, result)
    if text is None:
        return result

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        rows = list(reader)
    except csv.Error as exc:
        result.errors.append(CsvIssue(f"The file is not a valid CSV file: {exc}.", row=reader.line_num or None))
        return result

    header_index = next((i for i, row in enumerate(rows) if _has_content(row)), None)
    if header_index is None:
        result.errors.append(CsvIssue(f"The file is empty. The first line must be: {_EXPECTED_HEADER}"))
        return result

    header = [cell.strip().lower() for cell in rows[header_index]]
    header_row = header_index + 1
    if not _validate_header(header, header_row, result):
        return result

    data_rows = [
        (row_number, row)
        for row_number, row in enumerate(rows[header_index + 1 :], start=header_row + 1)
        if _has_content(row)
    ]
    if not data_rows:
        result.errors.append(CsvIssue("The file has a header but no transactions."))
        return result
    if len(data_rows) + existing_count > MAX_TRANSACTIONS_PER_PORTFOLIO:
        result.errors.append(
            CsvIssue(
                f"The file contains {len(data_rows)} transactions and the portfolio already has "
                f"{existing_count}; the maximum is {MAX_TRANSACTIONS_PER_PORTFOLIO:,}."
            )
        )
        return result

    # Running position per security, seeded with what is already stored, so a sale is judged
    # against the real holding rather than against the file alone.
    position: dict[tuple[str, str], int] = {}
    seen: dict[tuple, int] = {}
    for trade_date, symbol, exchange, kind, quantity in existing or []:
        key = (symbol, exchange)
        position[key] = position.get(key, 0) + (quantity if kind == "BUY" else -quantity)
        seen[(trade_date, symbol, exchange, kind, quantity)] = 0  # row 0 means "already stored"

    for row_number, row in data_rows:
        if len(row) != len(header):
            result.errors.append(
                CsvIssue(
                    f"Expected {len(header)} values but found {len(row)}. Check for missing or extra commas.",
                    row=row_number,
                )
            )
            continue

        values = dict(zip(header, row, strict=True))
        errors_before = len(result.errors)
        trade_date = _parse_cell(result, row_number, "trade_date", parse_trade_date, values["trade_date"])
        symbol = _parse_cell(result, row_number, "symbol", normalize_symbol, values["symbol"])
        exchange = _parse_cell(result, row_number, "exchange", normalize_exchange, values["exchange"])
        kind = _parse_cell(result, row_number, "type", normalize_kind, values["type"])
        quantity = _parse_cell(result, row_number, "quantity", parse_quantity, values["quantity"])
        price = _parse_cell(result, row_number, "price", parse_price, values["price"])
        fees = (
            _parse_cell(result, row_number, "fees", parse_fees, values["fees"])
            if "fees" in header
            else Decimal(0)
        )
        reference = (
            _parse_cell(result, row_number, "reference", normalize_reference, values["reference"])
            if "reference" in header
            else None
        )
        if len(result.errors) > errors_before:
            continue
        assert trade_date and symbol and exchange and kind and quantity and price is not None

        if trade_date > latest_session:
            result.errors.append(
                CsvIssue(
                    f"Trade date {trade_date:%d %b %Y} is after the latest completed NSE session "
                    f"({latest_session:%d %b %Y}).",
                    row=row_number,
                    column="trade_date",
                )
            )
            continue

        signature = (trade_date, symbol, exchange.value, kind, quantity)
        if signature in seen:
            where = (
                f"row {seen[signature]}"
                if seen[signature]
                else "a transaction already recorded for this portfolio"
            )
            result.errors.append(
                CsvIssue(
                    f"Duplicate transaction: {kind} {quantity} {symbol} on {trade_date:%d %b %Y} matches {where}. "
                    "Remove the duplicate, or change the reference if both really happened.",
                    row=row_number,
                )
            )
            continue
        seen[signature] = row_number

        key = (symbol, exchange.value)
        held = position.get(key, 0)
        if kind == "SELL" and quantity > held:
            result.errors.append(
                CsvIssue(
                    f"Sell quantity exceeds available quantity: selling {quantity} {symbol} on "
                    f"{trade_date:%d %b %Y} but only {held} held at that point.",
                    row=row_number,
                    column="quantity",
                )
            )
            continue
        position[key] = held + (quantity if kind == "BUY" else -quantity)

        result.transactions.append(
            TransactionInput(
                symbol=symbol,
                exchange=exchange,
                kind=kind,
                trade_date=trade_date,
                quantity=quantity,
                price=price,
                fees=fees or Decimal(0),
                reference=reference,
            )
        )

    # Rows out of date order are accepted but the running check above assumes file order, so say
    # so rather than letting a mis-ordered file produce a confusing oversell message.
    dates = [item.trade_date for item in result.transactions]
    if dates != sorted(dates):
        result.errors.append(
            CsvIssue(
                "Transactions are not in date order. Sort the file oldest first so that each sale "
                "can be checked against the position held at the time."
            )
        )
    return result


def _decode(content: bytes, result: TransactionCsvResult) -> str | None:
    if not content.strip():
        result.errors.append(CsvIssue(f"The file is empty. The first line must be: {_EXPECTED_HEADER}"))
        return None
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    result.errors.append(
        CsvIssue("The file could not be read as text. Save it as CSV with UTF-8 encoding and try again.")
    )
    return None


def _validate_header(header: list[str], header_row: int, result: TransactionCsvResult) -> bool:
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        result.errors.append(
            CsvIssue(
                f"Missing column{'s' if len(missing) > 1 else ''}: {', '.join(missing)}. "
                f"The first line must contain: {_EXPECTED_HEADER}",
                row=header_row,
            )
        )
        return False
    unsupported = [column for column in header if column not in CSV_COLUMNS]
    if unsupported:
        result.errors.append(
            CsvIssue(
                f"Unsupported column{'s' if len(unsupported) > 1 else ''}: {', '.join(unsupported)}. "
                f"Supported columns are: {', '.join(CSV_COLUMNS)}",
                row=header_row,
            )
        )
        return False
    duplicates = sorted({column for column in header if header.count(column) > 1})
    if duplicates:
        result.errors.append(
            CsvIssue(f"Column{'s' if len(duplicates) > 1 else ''} listed twice: {', '.join(duplicates)}.", row=header_row)
        )
        return False
    return True


def _parse_cell(
    result: TransactionCsvResult, row: int, column: str, parser: Callable[[object], T], value: str
) -> T | None:
    try:
        return parser(value)
    except ValueError as exc:
        result.errors.append(CsvIssue(str(exc), row=row, column=column))
        return None


def _has_content(row: list[str]) -> bool:
    return any(cell.strip() for cell in row)
