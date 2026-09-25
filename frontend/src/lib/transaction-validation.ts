/**
 * Client-side checks that mirror the transaction API's rules, so obvious mistakes are caught
 * before submission. The API validates everything again — this never decides what is stored.
 *
 * The one check that cannot be done here alone is the sell limit: how much is available depends
 * on the stored ledger, so the caller passes the position it knows about and the API remains the
 * authority.
 */

import type { Exchange, Transaction, TransactionInput, TransactionKind } from "@/lib/api";
// A relative path: the node test runner resolves imports itself and does not know the alias.
import { toUnits, unitsToDecimalString } from "./decimal.ts";

export const MAX_SYMBOL_LENGTH = 20;
export const MAX_REFERENCE_LENGTH = 64;
export const MAX_QUANTITY = 1_000_000_000;
export const EARLIEST_TRADE_DATE = "1994-11-03"; // NSE's equities segment began trading

const MAX_PRICE_UNITS = toUnits("9999999999.9999");
const ZERO = BigInt(0);
const SYMBOL_PATTERN = /^[A-Z0-9][A-Z0-9&-]*$/;
const NUMBER_PATTERN = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export type TransactionFormValues = {
  symbol: string;
  exchange: Exchange | "";
  kind: TransactionKind | "";
  tradeDate: string;
  quantity: string;
  price: string;
  fees: string;
  reference: string;
};

export type TransactionFormErrors = Partial<Record<keyof TransactionFormValues, string>>;

export const EMPTY_TRANSACTION_FORM: TransactionFormValues = {
  symbol: "",
  exchange: "NSE",
  kind: "BUY",
  tradeDate: "",
  quantity: "",
  price: "",
  fees: "",
  reference: "",
};

/** Quantity held per security, from the stored ledger. */
export function positionsFrom(transactions: readonly Transaction[]): Map<string, number> {
  const held = new Map<string, number>();
  for (const item of transactions) {
    const key = securityKey(item.symbol, item.exchange);
    const delta = item.kind === "BUY" ? item.quantity : -item.quantity;
    held.set(key, (held.get(key) ?? 0) + delta);
  }
  return held;
}

export function securityKey(symbol: string, exchange: string): string {
  return `${symbol}:${exchange}`;
}

/** Quantity × price, as a decimal string, or null when either value is unusable. */
export function grossValue(quantity: string, price: string): string | null {
  const parsedQuantity = parseQuantity(quantity);
  const parsedPrice = parseDecimal(price);
  if (typeof parsedQuantity === "string" || parsedPrice.error || parsedPrice.units === undefined) {
    return null;
  }
  return unitsToDecimalString(parsedPrice.units * BigInt(parsedQuantity));
}

/** Gross value adjusted for costs: what a buy takes out, or a sale brings in. */
export function netCashFlow(
  kind: TransactionKind | "",
  quantity: string,
  price: string,
  fees: string,
): string | null {
  const gross = grossValue(quantity, price);
  if (gross === null) return null;
  const parsedFees = fees.trim() ? parseDecimal(fees) : { units: ZERO, error: undefined };
  if (parsedFees.error || parsedFees.units === undefined) return null;
  const grossUnits = toUnits(gross);
  const units = kind === "SELL" ? -(grossUnits - parsedFees.units) : grossUnits + parsedFees.units;
  return signedDecimalString(units);
}

/**
 * Format units with a sign. The shared helper assumes a non-negative value — its remainder
 * carries the minus sign and produces strings like "-1.-500" — and a sale's cash flow is
 * negative by definition.
 */
export function signedDecimalString(units: bigint): string {
  const negative = units < BigInt(0);
  const text = unitsToDecimalString(negative ? -units : units);
  return negative ? `-${text}` : text;
}

export function validateTransaction(
  values: TransactionFormValues,
  options: { latestSession?: string; positions?: Map<string, number> } = {},
): { errors: TransactionFormErrors; transaction?: TransactionInput } {
  const errors: TransactionFormErrors = {};

  const symbol = values.symbol.trim().toUpperCase();
  if (!symbol) {
    errors.symbol = "Enter a stock symbol.";
  } else if (symbol.length > MAX_SYMBOL_LENGTH) {
    errors.symbol = `Use at most ${MAX_SYMBOL_LENGTH} characters.`;
  } else if (!SYMBOL_PATTERN.test(symbol)) {
    errors.symbol = "Use letters, digits, & or - only (for example HDFCBANK or M&M).";
  }

  if (values.exchange !== "NSE" && values.exchange !== "BSE") {
    errors.exchange = "Choose NSE or BSE.";
  }
  if (values.kind !== "BUY" && values.kind !== "SELL") {
    errors.kind = "Choose buy or sell.";
  }

  const tradeDate = values.tradeDate.trim();
  if (!tradeDate) {
    errors.tradeDate = "Enter the trade date.";
  } else if (!DATE_PATTERN.test(tradeDate) || Number.isNaN(Date.parse(tradeDate))) {
    errors.tradeDate = "Use the date picker, or type the date as YYYY-MM-DD.";
  } else if (tradeDate < EARLIEST_TRADE_DATE) {
    errors.tradeDate = "That date is before NSE began trading.";
  } else if (options.latestSession && tradeDate > options.latestSession) {
    errors.tradeDate = `A trade cannot be dated after the latest completed session (${options.latestSession}).`;
  }

  const quantity = parseQuantity(values.quantity);
  if (typeof quantity === "string") errors.quantity = quantity;

  const price = parseDecimal(values.price);
  if (price.error) {
    errors.price = price.error;
  } else if (price.units !== undefined && price.units <= ZERO) {
    errors.price = "Price must be greater than 0.";
  } else if (price.units !== undefined && price.units > MAX_PRICE_UNITS) {
    errors.price = "That price is too large.";
  }

  let fees = ZERO;
  if (values.fees.trim()) {
    const parsed = parseDecimal(values.fees);
    if (parsed.error) {
      errors.fees = parsed.error;
    } else if (parsed.units !== undefined && parsed.units < ZERO) {
      errors.fees = "Fees cannot be negative.";
    } else if (parsed.units !== undefined) {
      fees = parsed.units;
    }
  }

  const reference = values.reference.split(/\s+/).filter(Boolean).join(" ");
  if (reference.length > MAX_REFERENCE_LENGTH) {
    errors.reference = `Use at most ${MAX_REFERENCE_LENGTH} characters.`;
  }

  // A sale is only checkable against a position we know about; the API decides for certain.
  if (
    !errors.symbol &&
    !errors.quantity &&
    values.kind === "SELL" &&
    options.positions &&
    typeof quantity === "number"
  ) {
    const held = options.positions.get(securityKey(symbol, values.exchange || "NSE")) ?? 0;
    if (quantity > held) {
      errors.quantity = held
        ? `You hold ${held} ${symbol}. Selling ${quantity} is more than that.`
        : `No ${symbol} is held, so there is nothing to sell.`;
    }
  }

  if (Object.keys(errors).length > 0 || typeof quantity !== "number" || price.units === undefined) {
    return { errors };
  }

  return {
    errors,
    transaction: {
      symbol,
      exchange: values.exchange as Exchange,
      kind: values.kind as TransactionKind,
      trade_date: tradeDate,
      quantity,
      price: unitsToDecimalString(price.units),
      fees: unitsToDecimalString(fees),
      reference: reference || null,
    },
  };
}

function parseQuantity(value: string): number | string {
  const text = value.trim();
  if (!text) return "Enter a quantity.";
  if (!NUMBER_PATTERN.test(text)) return "Enter a whole number of shares.";
  const parsed = Number(text);
  if (!Number.isInteger(parsed)) return "Quantity must be a whole number of shares.";
  if (parsed <= 0) return "Quantity must be greater than 0.";
  if (parsed > MAX_QUANTITY) return `Quantity must be at most ${MAX_QUANTITY.toLocaleString("en-IN")}.`;
  return parsed;
}

function parseDecimal(value: string): { units?: bigint; error?: string } {
  const text = value.trim();
  if (!text) return { error: "Enter an amount." };
  if (!NUMBER_PATTERN.test(text)) {
    return { error: "Enter a number using digits and an optional decimal point." };
  }
  const [, decimals = ""] = text.split(".");
  if (decimals.length > 4) return { error: "Use at most 4 decimal places." };
  return { units: toUnits(text) };
}

export type PositionDifference = { symbol: string; exchange: string; ledger: number; holdings: number };

/**
 * Compare the ledger's closing position with the holdings on record.
 *
 * Presentational only: the authoritative reconciliation comes from the performance API, which
 * uses the same rule. Neither source is ever rewritten to match the other — a difference means
 * the user's records disagree, and only they can say which is right.
 */
export function reconcile(
  transactions: readonly Transaction[],
  holdings: readonly { symbol: string; exchange: string; quantity: number }[],
): { reconciled: boolean; differences: PositionDifference[] } {
  const ledger = positionsFrom(transactions);
  const declared = new Map(holdings.map((item) => [securityKey(item.symbol, item.exchange), item.quantity]));
  const keys = [...new Set([...ledger.keys(), ...declared.keys()])].sort();

  const differences: PositionDifference[] = [];
  for (const key of keys) {
    const fromLedger = ledger.get(key) ?? 0;
    const fromHoldings = declared.get(key) ?? 0;
    if (fromLedger !== fromHoldings) {
      const [symbol, exchange] = key.split(":");
      differences.push({ symbol, exchange, ledger: fromLedger, holdings: fromHoldings });
    }
  }
  return { reconciled: differences.length === 0, differences };
}
