// Unit tests for valuation display rules. Run with `npm test` (Node's built-in test runner).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  STATUS_TEXT,
  describePriceBasis,
  formatPercent,
  formatSignedInr,
  formatSignedPercent,
  formatTradeDate,
  summarizeValuation,
  toneOf,
  unpricedReasonText,
  valuationNotices,
} from "./valuation-display.ts";

const TRADE_DATE = /^14 Sept? 2026$/;

function holding(overrides = {}) {
  return {
    holding_id: "h1",
    symbol: "RELIANCE",
    exchange: "NSE",
    quantity: 10,
    average_buy_price: "2400.00",
    status: "VALUED",
    unpriced_reason: null,
    price: {
      close_price: "2650.00",
      trade_date: "2026-09-14",
      exchange: "NSE",
      source: "indian_api",
      source_name: "Indian API",
      fetched_at: "2026-09-14T13:00:00Z",
    },
    invested_value: "24000.00",
    market_value: "26500.00",
    unrealized_pnl: "2500.00",
    unrealized_return_pct: "10.42",
    weight_pct: "100.00",
    warnings: [],
    ...overrides,
  };
}

function valuation(overrides = {}) {
  return {
    portfolio_id: "p1",
    portfolio_name: "Test",
    valued_at: "2026-09-14T13:00:00Z",
    market_data_configured: true,
    methodology: { price_basis: "NSE_EOD_CLOSE", currency: "INR", rounding: "", note: "" },
    freshness: {
      expected_session_date: "2026-09-14",
      latest_price_date: "2026-09-14",
      oldest_price_date: "2026-09-14",
      valued_count: 1,
      stale_count: 0,
      unpriced_count: 0,
    },
    totals: {
      total_invested_value: "24000.00",
      priced_invested_value: "24000.00",
      total_market_value: "26500.00",
      total_unrealized_pnl: "2500.00",
      total_unrealized_return_pct: "10.42",
      is_complete: true,
    },
    holdings: [holding()],
    ...overrides,
  };
}

test("signed amounts and percentages always show the sign in text", () => {
  assert.equal(formatSignedInr("2500.00"), "+₹2,500.00");
  assert.equal(formatSignedInr("-3000.00"), "-₹3,000.00");
  assert.equal(formatSignedInr("0.00"), "₹0.00");
  assert.equal(formatSignedInr("123456.78"), "+₹1,23,456.78");
  assert.equal(formatSignedPercent("10.42"), "+10.42%");
  assert.equal(formatSignedPercent("-14.29"), "-14.29%");
  assert.equal(formatPercent("60.00"), "60.00%");
});

test("tone follows the sign", () => {
  assert.equal(toneOf("2500.00"), "positive");
  assert.equal(toneOf("-0.01"), "negative");
  assert.equal(toneOf("0.00"), "neutral");
});

test("trade dates are not shifted by the viewer's time zone", () => {
  assert.match(formatTradeDate("2026-09-14"), TRADE_DATE);
});

test("price basis names the exchange, the EOD basis and the date", () => {
  assert.match(describePriceBasis(valuation()), /^Valuation based on NSE EOD closing prices dated 14 Sept? 2026\.$/);
  const mixed = valuation({ freshness: { ...valuation().freshness, oldest_price_date: "2026-09-11" } });
  assert.match(describePriceBasis(mixed), /dated between 11 Sept? 2026 and 14 Sept? 2026\.$/);
  const none = valuation({ freshness: { ...valuation().freshness, latest_price_date: null, oldest_price_date: null } });
  assert.equal(describePriceBasis(none), null);
});

test("summary distinguishes complete, partial, unpriced and empty valuations", () => {
  assert.equal(summarizeValuation(valuation()), "complete");
  assert.equal(summarizeValuation(valuation({ totals: { ...valuation().totals, is_complete: false } })), "partial");
  assert.equal(
    summarizeValuation(valuation({ totals: { ...valuation().totals, total_market_value: null, is_complete: false } })),
    "unpriced",
  );
  assert.equal(summarizeValuation(valuation({ holdings: [] })), "empty");
});

test("unpriced holdings explain why instead of showing zero", () => {
  assert.equal(
    unpricedReasonText("NO_PRICE_DATA"),
    "Price unavailable — this holding cannot currently be valued from the supported NSE EOD dataset.",
  );
  assert.match(unpricedReasonText("NO_NSE_LISTING"), /no NSE listing/);
  assert.match(unpricedReasonText("LISTING_NOT_FOUND"), /not found/);
  assert.equal(STATUS_TEXT.UNPRICED.label, "Unpriced");
  assert.equal(STATUS_TEXT.STALE.label, "Stale");
  assert.equal(STATUS_TEXT.VALUED.label, "Valued");
});

test("a complete, fresh valuation has no notices", () => {
  assert.deepEqual(valuationNotices(valuation()), []);
});

test("stale, unpriced, large-move and configuration notices are raised", () => {
  const notices = valuationNotices(
    valuation({
      market_data_configured: false,
      freshness: { ...valuation().freshness, stale_count: 1, unpriced_count: 2 },
      holdings: [holding({ warnings: ["LARGE_PRICE_MOVE"] })],
    }),
  );
  const titles = notices.map((notice) => notice.title);
  assert.deepEqual(titles, [
    "1 holding uses an older closing price",
    "2 holdings could not be valued",
    "Large price move detected",
    "Market-data sync is not configured",
  ]);
  assert.match(notices[1].body, /excluded from Current Value/);
  assert.match(notices[2].body, /RELIANCE/);
});
