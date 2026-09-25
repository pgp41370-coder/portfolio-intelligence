import assert from "node:assert/strict";
import { test } from "node:test";
import {
  basisLabel,
  buildChartGeometry,
  buildComparisonGeometry,
  concentrationSummary,
  coverageNotice,
  rangeStart,
} from "./performance-display.ts";

const BOX = { width: 100, height: 40, padding: 4 };
const points = (...values) =>
  values.map((value, index) => ({ trade_date: `2026-09-${String(14 + index).padStart(2, "0")}`, value }));

test("chart geometry spans the box and tracks the values", () => {
  const geometry = buildChartGeometry(points("100", "150", "200"), BOX);
  assert.ok(geometry);
  assert.equal(geometry.min, 100);
  assert.equal(geometry.max, 200);
  assert.ok(geometry.line.startsWith("M4,36"), geometry.line); // lowest value sits on the lower edge
  assert.ok(geometry.line.includes("96,4")); // highest value on the upper edge
  assert.ok(geometry.area.endsWith("Z"));
  assert.equal(geometry.first.value, "100");
  assert.equal(geometry.last.value, "200");
});

test("a flat series is drawn through the middle, not the floor", () => {
  const geometry = buildChartGeometry(points("500", "500", "500"), BOX);
  assert.ok(geometry);
  assert.ok(geometry.line.includes("4,20"), geometry.line);
});

test("a chart needs at least two points and finite values", () => {
  assert.equal(buildChartGeometry([], BOX), null);
  assert.equal(buildChartGeometry(points("100"), BOX), null);
  assert.equal(buildChartGeometry(points("100", "oops"), BOX), null);
});

test("range start dates are derived from the last session", () => {
  assert.equal(rangeStart("2026-09-23", "1M"), "2026-08-23");
  assert.equal(rangeStart("2026-09-23", "6M"), "2026-03-23");
  assert.equal(rangeStart("2026-09-23", "1Y"), "2025-09-23");
  assert.equal(rangeStart("2026-09-23", "MAX"), undefined);
  assert.equal(rangeStart("not-a-date", "1M"), undefined);
});

test("complete coverage says nothing; gaps are spelled out", () => {
  assert.equal(
    coverageNotice({ status: "complete", sessions_available: 20, sessions_expected: 20, missing_session_count: 0 }),
    null,
  );

  const partial = coverageNotice({
    status: "partial",
    sessions_available: 19,
    sessions_expected: 20,
    missing_session_count: 1,
  });
  assert.equal(partial.tone, "caution");
  assert.match(partial.text, /19 of 20 sessions priced/);
  assert.match(partial.text, /1 session had no complete set of closes and was left out/);

  const closure = coverageNotice({
    status: "partial",
    sessions_available: 248,
    sessions_expected: 252,
    missing_session_count: 4,
    missing_no_prices_at_all_count: 4,
    missing_some_prices_count: 0,
  });
  assert.match(closure.text, /exchange was closed on a day the trading calendar does not list/);

  const mixed = coverageNotice({
    status: "partial",
    sessions_available: 248,
    sessions_expected: 252,
    missing_session_count: 4,
    missing_no_prices_at_all_count: 3,
    missing_some_prices_count: 1,
  });
  assert.match(mixed.text, /3 of them have no price for any holding; the other 1 is missing prices for some holdings/);

  const insufficient = coverageNotice({
    status: "insufficient",
    sessions_available: 1,
    sessions_expected: 1,
    missing_session_count: 0,
  });
  assert.match(insufficient.text, /Not enough priced sessions/);
});

test("the basis is labelled honestly", () => {
  assert.equal(basisLabel("CURRENT_HOLDINGS").label, "Reconstructed");
  assert.match(basisLabel("CURRENT_HOLDINGS").explanation, /no transaction history/);
  assert.equal(basisLabel("TRANSACTIONS").label, "Transaction-aware");
  assert.match(basisLabel("TRANSACTIONS").explanation, /time-weighted/);
});

// --- Portfolio versus benchmark (M4.2) ---------------------------------------------------

const growth = (...values) =>
  values.map((value, index) => ({
    trade_date: `2026-09-${String(14 + index).padStart(2, "0")}`,
    cumulative_return_pct: String(value),
  }));

const benchmarkSeries = (...values) =>
  values.map((value, index) => ({
    trade_date: `2026-09-${String(14 + index).padStart(2, "0")}`,
    index: String(value),
  }));

test("comparison chart plots both series as the growth of 100", () => {
  const geometry = buildComparisonGeometry(growth(0, 10, 21), benchmarkSeries(100, 105, 110.25), BOX);

  assert.ok(geometry);
  assert.ok(geometry.benchmark, "a benchmark line is drawn when the series overlaps");
  assert.equal(geometry.min, 100); // both start at 100
  assert.equal(geometry.max, 121); // the portfolio's 21% gain is the top of the range
  assert.equal(geometry.firstDate, "2026-09-14");
  assert.equal(geometry.lastDate, "2026-09-16");
  assert.ok(geometry.portfolio.area, "the portfolio line is filled");
  assert.equal(geometry.benchmark.area, null, "the benchmark is a line only");
});

test("comparison rebases to the first session the two series share", () => {
  // The benchmark's history starts a day late, as a real ETF series can.
  const geometry = buildComparisonGeometry(
    growth(0, 10, 21),
    [{ trade_date: "2026-09-15", index: "200" }, { trade_date: "2026-09-16", index: "220" }],
    BOX,
  );

  assert.ok(geometry.benchmark);
  // Rebased at 15 Sep: the portfolio's 110 becomes 100, and its 121 becomes 110.
  assert.ok(Math.abs(geometry.min - 90.909) < 0.001, String(geometry.min)); // 100/110 x 100
  assert.ok(Math.abs(geometry.max - 110) < 0.001, String(geometry.max));
});

test("comparison degrades to a single line when the benchmark cannot be aligned", () => {
  const geometry = buildComparisonGeometry(growth(0, 10), benchmarkSeries(), BOX);

  assert.ok(geometry);
  assert.equal(geometry.benchmark, null, "no benchmark line is invented");
});

test("comparison needs at least two portfolio points", () => {
  assert.equal(buildComparisonGeometry(growth(0), benchmarkSeries(100), BOX), null);
});

test("concentration summary explains the band with the effective holding count", () => {
  assert.match(
    concentrationSummary("highly concentrated", "2.5"),
    /highly concentrated: its weights behave like about 2.5 equally sized positions/,
  );
  assert.equal(concentrationSummary(null, "2.5"), null);
  assert.match(concentrationSummary("diversified", null), /This portfolio is diversified\./);
});
