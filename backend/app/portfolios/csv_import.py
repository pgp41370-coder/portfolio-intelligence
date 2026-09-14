"""Parse and validate holdings CSV files.

Accepted format (header required, column order free, names case-insensitive):

    symbol,exchange,quantity,average_buy_price
    HDFCBANK,NSE,20,1650

Parsing uses Python's standard csv module on decoded text only: cell values are
treated as plain strings, no formulas are evaluated, nothing is executed and
nothing is written to disk. An upload is either entirely valid or rejected.
"""

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from app.portfolios.rules import (
    MAX_HOLDINGS_PER_PORTFOLIO,
    Exchange,
    normalize_exchange,
    normalize_symbol,
    parse_average_buy_price,
    parse_quantity,
)
from app.portfolios.schemas import HoldingInput

CSV_COLUMNS = ("symbol", "exchange", "quantity", "average_buy_price")
MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_SIZE_LABEL = "1 MB"
# Browsers report CSV files inconsistently (Windows often uses application/vnd.ms-excel).
ALLOWED_CSV_CONTENT_TYPES = frozenset(
    {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel", "application/octet-stream", ""}
)

_EXPECTED_HEADER = ",".join(CSV_COLUMNS)
T = TypeVar("T")


@dataclass(frozen=True)
class CsvIssue:
    message: str
    row: int | None = None
    column: str | None = None


@dataclass
class CsvParseResult:
    holdings: list[HoldingInput] = field(default_factory=list)
    errors: list[CsvIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def parse_holdings_csv(content: bytes) -> CsvParseResult:
    """Validate every row. Row numbers count the header as row 1, as in a spreadsheet."""
    result = CsvParseResult()

    text = _decode(content, result)
    if text is None:
        return result

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        rows = list(reader)
    except csv.Error as exc:
        result.errors.append(
            CsvIssue(f"The file is not a valid CSV file: {exc}.", row=reader.line_num or None)
        )
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
        result.errors.append(CsvIssue("The file has a header but no holdings."))
        return result
    if len(data_rows) > MAX_HOLDINGS_PER_PORTFOLIO:
        result.errors.append(
            CsvIssue(
                f"The file contains {len(data_rows)} holdings; the maximum is {MAX_HOLDINGS_PER_PORTFOLIO}."
            )
        )
        return result

    first_seen: dict[tuple[str, Exchange], int] = {}
    for row_number, row in data_rows:
        if len(row) != len(header):
            result.errors.append(
                CsvIssue(
                    f"Expected {len(header)} values but found {len(row)}. "
                    "Check for missing or extra commas.",
                    row=row_number,
                )
            )
            continue

        values = dict(zip(header, row, strict=True))
        errors_before = len(result.errors)
        symbol = _parse_cell(result, row_number, "symbol", normalize_symbol, values["symbol"])
        exchange = _parse_cell(result, row_number, "exchange", normalize_exchange, values["exchange"])
        quantity = _parse_cell(result, row_number, "quantity", parse_quantity, values["quantity"])
        price = _parse_cell(
            result, row_number, "average_buy_price", parse_average_buy_price, values["average_buy_price"]
        )
        if len(result.errors) > errors_before or symbol is None or exchange is None:
            continue

        key = (symbol, exchange)
        if key in first_seen:
            result.errors.append(
                CsvIssue(
                    f"Duplicate holding: {symbol} on {exchange} is also listed on row {first_seen[key]}. "
                    "List each holding once, then upload the file again.",
                    row=row_number,
                    column="symbol",
                )
            )
            continue
        first_seen[key] = row_number
        result.holdings.append(
            HoldingInput(symbol=symbol, exchange=exchange, quantity=quantity, average_buy_price=price)
        )

    return result


def _decode(content: bytes, result: CsvParseResult) -> str | None:
    if not content.strip():
        result.errors.append(CsvIssue(f"The file is empty. The first line must be: {_EXPECTED_HEADER}"))
        return None
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        result.errors.append(
            CsvIssue("The file is not UTF-8 text. Save it as 'CSV UTF-8' and upload it again.")
        )
        return None
    if "\x00" in text:
        result.errors.append(CsvIssue("The file contains binary data and is not a CSV file."))
        return None
    return text


def _validate_header(header: list[str], header_row: int, result: CsvParseResult) -> bool:
    def label(name: str) -> str:
        return name or "(blank)"

    duplicates = sorted({name for name in header if header.count(name) > 1})
    missing = [name for name in CSV_COLUMNS if name not in header]
    unexpected = [name for name in header if name not in CSV_COLUMNS]

    if duplicates:
        result.errors.append(
            CsvIssue(f"Duplicate column(s) in the header: {', '.join(map(label, duplicates))}.", row=header_row)
        )
    if missing:
        result.errors.append(
            CsvIssue(
                f"Missing required column(s): {', '.join(missing)}. The header must be: {_EXPECTED_HEADER}",
                row=header_row,
            )
        )
    if unexpected:
        result.errors.append(
            CsvIssue(
                f"Unexpected column(s): {', '.join(map(label, unexpected))}. "
                f"Only these columns are accepted: {_EXPECTED_HEADER}",
                row=header_row,
            )
        )
    return not (duplicates or missing or unexpected)


def _parse_cell(
    result: CsvParseResult,
    row_number: int,
    column: str,
    parser: Callable[[str], T],
    raw_value: str,
) -> T | None:
    try:
        return parser(raw_value)
    except ValueError as exc:
        result.errors.append(CsvIssue(str(exc), row=row_number, column=column))
        return None


def _has_content(row: list[str]) -> bool:
    return any(cell.strip() for cell in row)
