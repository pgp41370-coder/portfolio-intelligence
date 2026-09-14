/**
 * Client-side checks that mirror the API's validation rules, so obvious mistakes
 * are caught before submission. The API validates everything again.
 */

import type { Exchange, HoldingInput } from "@/lib/api";
import { toUnits, unitsToDecimalString } from "@/lib/decimal";

export const MAX_PORTFOLIO_NAME_LENGTH = 100;
export const MAX_SYMBOL_LENGTH = 20;
export const MAX_HOLDINGS = 500;
export const MAX_CSV_BYTES = 1024 * 1024;

const MAX_QUANTITY = 1_000_000_000;
const MAX_PRICE_UNITS = toUnits("9999999999.9999");
const ZERO = BigInt(0);
const SYMBOL_PATTERN = /^[A-Z0-9][A-Z0-9&-]*$/;
const NUMBER_PATTERN = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

export type HoldingFormValues = {
  symbol: string;
  exchange: Exchange | "";
  quantity: string;
  averageBuyPrice: string;
};

export type HoldingFormErrors = Partial<Record<keyof HoldingFormValues, string>>;

export function normalizePortfolioName(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

export function validatePortfolioName(value: string): string | undefined {
  const name = normalizePortfolioName(value);
  if (!name) return "Enter a portfolio name.";
  if (name.length > MAX_PORTFOLIO_NAME_LENGTH) {
    return `Use at most ${MAX_PORTFOLIO_NAME_LENGTH} characters.`;
  }
  return undefined;
}

export function validateHolding(
  values: HoldingFormValues,
  existing: readonly HoldingInput[],
): { errors: HoldingFormErrors; holding?: HoldingInput } {
  const errors: HoldingFormErrors = {};

  const symbol = values.symbol.trim().toUpperCase();
  if (!symbol) {
    errors.symbol = "Enter a stock symbol.";
  } else if (symbol.length > MAX_SYMBOL_LENGTH) {
    errors.symbol = `Use at most ${MAX_SYMBOL_LENGTH} characters.`;
  } else if (!SYMBOL_PATTERN.test(symbol)) {
    errors.symbol = "Use letters, digits, & or - only (for example HDFCBANK or M&M).";
  }

  const exchange = values.exchange;
  if (exchange !== "NSE" && exchange !== "BSE") {
    errors.exchange = "Choose NSE or BSE.";
  }

  const quantity = parseQuantity(values.quantity);
  if (typeof quantity === "string") errors.quantity = quantity;

  const price = parsePrice(values.averageBuyPrice);
  if (price.error) errors.averageBuyPrice = price.error;

  if (
    !errors.symbol &&
    !errors.exchange &&
    existing.some((holding) => holding.symbol === symbol && holding.exchange === exchange)
  ) {
    errors.symbol = `${symbol} on ${exchange} is already in the list. Remove it first to change it.`;
  }

  if (Object.keys(errors).length > 0 || typeof quantity !== "number" || !price.value) {
    return { errors };
  }
  return {
    errors,
    holding: {
      symbol,
      exchange: exchange as Exchange,
      quantity,
      average_buy_price: price.value,
    },
  };
}

function parseQuantity(raw: string): number | string {
  const text = raw.trim();
  if (!text) return "Enter a quantity.";
  if (!NUMBER_PATTERN.test(text)) return "Enter a number using digits only, without commas.";
  const quantity = Number(text);
  if (quantity <= 0) return "Quantity must be greater than 0.";
  if (!Number.isInteger(quantity)) return "Quantity must be a whole number of shares.";
  if (quantity > MAX_QUANTITY) return "Quantity is too large.";
  return quantity;
}

function parsePrice(raw: string): { value?: string; error?: string } {
  const text = raw.trim();
  if (!text) return { error: "Enter the average buy price." };
  if (!NUMBER_PATTERN.test(text)) {
    return { error: "Enter a number without commas or the ₹ symbol." };
  }
  if (text.startsWith("-")) return { error: "Average buy price must be greater than 0." };
  const fraction = text.split(".")[1]?.replace(/0+$/, "") ?? "";
  if (fraction.length > 4) return { error: "Use at most 4 decimal places." };
  const units = toUnits(text);
  if (units <= ZERO) return { error: "Average buy price must be greater than 0." };
  if (units > MAX_PRICE_UNITS) return { error: "Average buy price is too large." };
  return { value: unitsToDecimalString(units) };
}
