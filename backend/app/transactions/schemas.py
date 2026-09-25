"""Request and response models for the transaction ledger."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator

from app.portfolios.rules import Exchange, normalize_exchange, normalize_symbol
from app.portfolios.schemas import CsvIssueRead
from app.transactions.rules import (
    normalize_kind,
    normalize_reference,
    parse_fees,
    parse_price,
    parse_quantity,
    parse_trade_date,
)
from app.valuation.calculations import format_money

Money = Annotated[Decimal, PlainSerializer(format_money, return_type=str)]


class TransactionInput(BaseModel):
    """One buy or sell. Quantities are always positive; direction comes from ``kind``."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange: Exchange
    kind: Literal["BUY", "SELL"]
    trade_date: date
    quantity: int
    price: Decimal
    fees: Decimal = Decimal(0)
    reference: str | None = None

    @field_validator("symbol", mode="before")
    @classmethod
    def _symbol(cls, value: object) -> str:
        return normalize_symbol(value)

    @field_validator("exchange", mode="before")
    @classmethod
    def _exchange(cls, value: object) -> Exchange:
        return normalize_exchange(value)

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value: object) -> str:
        return normalize_kind(value)

    @field_validator("trade_date", mode="before")
    @classmethod
    def _trade_date(cls, value: object) -> date:
        return parse_trade_date(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def _quantity(cls, value: object) -> int:
        return parse_quantity(value)

    @field_validator("price", mode="before")
    @classmethod
    def _price(cls, value: object) -> Decimal:
        return parse_price(value)

    @field_validator("fees", mode="before")
    @classmethod
    def _fees(cls, value: object) -> Decimal:
        return parse_fees(value)

    @field_validator("reference", mode="before")
    @classmethod
    def _reference(cls, value: object) -> str | None:
        return normalize_reference(value)


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    symbol: str
    exchange: Exchange
    kind: str
    trade_date: date
    quantity: int
    price: Money
    fees: Money
    reference: str | None
    created_at: datetime


class TransactionListRead(BaseModel):
    portfolio_id: uuid.UUID
    portfolio_name: str
    count: int
    transactions: list[TransactionRead]


class TransactionCsvPreviewRead(BaseModel):
    """What a CSV would add, or every reason it cannot be imported.

    A preview never writes anything. ``is_valid`` false means the import would be refused in
    full: the ledger is imported atomically, because a partly imported ledger produces a wrong
    cost basis and a wrong return without saying so.
    """

    is_valid: bool
    transaction_count: int
    transactions: list[TransactionInput]
    net_cash_flow: Money | None
    errors: list["CsvIssueRead"]
