import assert from "node:assert/strict";
import test from "node:test";
import {
  EMPTY_TRANSACTION_FORM,
  grossValue,
  netCashFlow,
  positionsFrom,
  securityKey,
  signedDecimalString,
  validateTransaction,
} from "./transaction-validation.ts";

const form = (overrides) => ({
  ...EMPTY_TRANSACTION_FORM,
  symbol: "RELIANCE",
  tradeDate: "2026-09-14",
  quantity: "10",
  price: "1234.50",
  ...overrides,
});

const stored = (overrides = {}) => ({
  id: "1",
  symbol: "RELIANCE",
  exchange: "NSE",
  kind: "BUY",
  trade_date: "2026-09-14",
  quantity: 10,
  price: "100.0000",
  fees: "0.0000",
  reference: null,
  created_at: "2026-09-14T10:00:00Z",
  ...overrides,
});

test("a complete form produces a transaction the API will accept", () => {
  const { errors, transaction } = validateTransaction(form({ fees: "23.6", reference: " ORD 1 " }));

  assert.deepEqual(errors, {});
  assert.equal(transaction.symbol, "RELIANCE");
  assert.equal(transaction.kind, "BUY");
  assert.equal(transaction.quantity, 10);
  assert.equal(transaction.price, "1234.5000");
  assert.equal(transaction.fees, "23.6000");
  assert.equal(transaction.reference, "ORD 1");
});

test("symbols are upper-cased and checked for shape", () => {
  assert.equal(validateTransaction(form({ symbol: " reliance " })).transaction.symbol, "RELIANCE");
  assert.match(validateTransaction(form({ symbol: "" })).errors.symbol, /Enter a stock symbol/);
  assert.match(validateTransaction(form({ symbol: "BAD SYMBOL" })).errors.symbol, /letters, digits/);
  assert.equal(validateTransaction(form({ symbol: "M&M" })).errors.symbol, undefined);
});

test("quantity must be a whole positive number of shares", () => {
  assert.match(validateTransaction(form({ quantity: "" })).errors.quantity, /Enter a quantity/);
  assert.match(validateTransaction(form({ quantity: "0" })).errors.quantity, /greater than 0/);
  assert.match(validateTransaction(form({ quantity: "-5" })).errors.quantity, /greater than 0/);
  assert.match(validateTransaction(form({ quantity: "1.5" })).errors.quantity, /whole number/);
  assert.match(validateTransaction(form({ quantity: "ten" })).errors.quantity, /whole number/);
});

test("price must be positive and sensibly precise", () => {
  assert.match(validateTransaction(form({ price: "0" })).errors.price, /greater than 0/);
  assert.match(validateTransaction(form({ price: "-1" })).errors.price, /greater than 0/);
  assert.match(validateTransaction(form({ price: "1.234567" })).errors.price, /4 decimal places/);
  assert.match(validateTransaction(form({ price: "abc" })).errors.price, /number using digits/);
});

test("fees are optional but never negative", () => {
  assert.equal(validateTransaction(form({ fees: "" })).transaction.fees, "0.0000");
  assert.match(validateTransaction(form({ fees: "-1" })).errors.fees, /cannot be negative/);
});

test("trade dates are bounded at both ends", () => {
  assert.match(validateTransaction(form({ tradeDate: "" })).errors.tradeDate, /Enter the trade date/);
  assert.match(validateTransaction(form({ tradeDate: "14-09-2026" })).errors.tradeDate, /YYYY-MM-DD/);
  assert.match(validateTransaction(form({ tradeDate: "1990-01-01" })).errors.tradeDate, /before NSE began/);
  const future = validateTransaction(form({ tradeDate: "2026-09-20" }), { latestSession: "2026-09-18" });
  assert.match(future.errors.tradeDate, /after the latest completed session/);
});

test("a sale is checked against the position actually held", () => {
  const positions = positionsFrom([stored({ quantity: 10 })]);

  const tooMany = validateTransaction(form({ kind: "SELL", quantity: "11" }), { positions });
  assert.match(tooMany.errors.quantity, /You hold 10 RELIANCE/);

  const exact = validateTransaction(form({ kind: "SELL", quantity: "10" }), { positions });
  assert.equal(exact.errors.quantity, undefined);

  const nothingHeld = validateTransaction(form({ kind: "SELL", symbol: "TCS", quantity: "1" }), { positions });
  assert.match(nothingHeld.errors.quantity, /nothing to sell/);
});

test("positions net buys against sells per security and exchange", () => {
  const positions = positionsFrom([
    stored({ id: "1", quantity: 10 }),
    stored({ id: "2", kind: "SELL", quantity: 4 }),
    stored({ id: "3", symbol: "TCS", quantity: 5 }),
  ]);

  assert.equal(positions.get(securityKey("RELIANCE", "NSE")), 6);
  assert.equal(positions.get(securityKey("TCS", "NSE")), 5);
  assert.equal(positions.get(securityKey("INFY", "NSE")), undefined);
});

test("gross value multiplies exactly, without floating point drift", () => {
  assert.equal(grossValue("3", "0.1"), "0.3000");
  assert.equal(grossValue("10", "1234.5678"), "12345.6780");
  assert.equal(grossValue("0", "10"), null);
  assert.equal(grossValue("10", "abc"), null);
});

test("a buy's cash flow adds fees and a sale's subtracts them", () => {
  assert.equal(netCashFlow("BUY", "10", "100", "25"), "1025.0000");
  assert.equal(netCashFlow("SELL", "10", "100", "25"), "-975.0000");
  assert.equal(netCashFlow("BUY", "10", "100", ""), "1000.0000");
});

test("negative amounts format with a leading sign, not a broken fraction", () => {
  // The shared helper alone would render this as "-1.-500".
  assert.equal(signedDecimalString(BigInt(-10500)), "-1.0500");
  assert.equal(signedDecimalString(BigInt(10500)), "1.0500");
  assert.equal(signedDecimalString(BigInt(0)), "0.0000");
});
