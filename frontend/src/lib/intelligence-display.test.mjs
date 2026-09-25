import assert from "node:assert/strict";
import test from "node:test";
import {
  formatPoints,
  intelligenceView,
  measuredOrDash,
  moneyWeightedView,
  priceAnomalyHeading,
} from "./performance-display.ts";

const base = (overrides = {}) => ({
  status: "available",
  headline: "Portfolio time-weighted return was -19.69% over 236 priced sessions.",
  returns: {},
  data_quality: { limitations: [], benchmark_status: "available", benchmark_basis: "ETF_PROXY", ...(overrides.quality ?? {}) },
  ...overrides,
});

test("an available explanation shows its sections without a badge", () => {
  const view = intelligenceView(base());

  assert.equal(view.showSections, true);
  assert.equal(view.badge, null);
  assert.equal(view.emptyReason, null);
  assert.equal(view.benchmarkLabel, "Index ETF used as a proxy");
});

test("a qualified explanation is badged and counts its limitations", () => {
  const view = intelligenceView(
    base({ status: "limited", quality: { limitations: ["7 sessions behind.", "Ledger differs."] } }),
  );

  assert.equal(view.badge, "qualified");
  assert.equal(view.showSections, true, "a qualified explanation is still shown");
  assert.equal(view.limitationCount, 2);
});

test("an unavailable explanation shows the reason instead of empty sections", () => {
  const view = intelligenceView(base({ status: "unavailable", returns: null, headline: "Not enough priced history." }));

  assert.equal(view.showSections, false);
  assert.equal(view.emptyReason, "Not enough priced history.");
});

test("a missing returns block is treated as unavailable even if the status disagrees", () => {
  const view = intelligenceView(base({ returns: null }));

  assert.equal(view.showSections, false);
});

test("the benchmark label never claims an index when there is only a proxy", () => {
  assert.equal(
    intelligenceView(base({ quality: { limitations: [], benchmark_status: "no_data", benchmark_basis: "ETF_PROXY" } }))
      .benchmarkLabel,
    "No benchmark comparison",
  );
  assert.equal(
    intelligenceView(base({ quality: { limitations: [], benchmark_status: "available", benchmark_basis: "INDEX" } }))
      .benchmarkLabel,
    "Benchmark",
  );
});

test("an unmeasured figure shows a dash, never a zero", () => {
  assert.equal(measuredOrDash(null), "—");
  assert.equal(measuredOrDash(""), "—");
  assert.equal(measuredOrDash("0.00"), "0.00%");
  assert.equal(measuredOrDash("-31.64"), "-31.64%");
  assert.equal(measuredOrDash("1.06", ""), "1.06");
});

test("a contribution is shown in percentage points, not percent", () => {
  // "+4.80% pts" would read as a different quantity from "+4.80 pts".
  assert.equal(formatPoints("4.80"), "+4.80 pts");
  assert.equal(formatPoints("-13.04"), "-13.04 pts");
  assert.equal(formatPoints("0"), "0.00 pts");
  assert.equal(formatPoints("not a number"), "—");
});

// --- Money-weighted presentation (M6.1) ---------------------------------------------------

const money = (overrides = {}) => ({
  status: "available",
  annualised_pct: "-30.02",
  period_pct: "-28.91",
  period_days: 349,
  annualisation_note: null,
  disclosure: null,
  note: "Measured from the investor's own cash flows.",
  roots_found: 1,
  ...overrides,
});

test("an available money-weighted return shows both figures", () => {
  const view = moneyWeightedView(money());

  assert.equal(view.showFigures, true);
  assert.equal(view.periodLabel, "349-day");
  assert.equal(view.annualisedLabel, "Annualised");
  assert.equal(view.statusLabel, null);
});

test("a portfolio without a ledger shows no money-weighted section at all", () => {
  assert.equal(moneyWeightedView(money({ status: "not_applicable" })), null);
  assert.equal(moneyWeightedView(null), null);
});

test("ambiguous roots show the reason and never a figure", () => {
  const view = moneyWeightedView(
    money({ status: "ambiguous_multiple_roots", annualised_pct: null, period_pct: null, roots_found: 2 }),
  );

  assert.equal(view.showFigures, false);
  assert.match(view.statusLabel, /2 different rates fit these cash flows/);
  assert.ok(view.notes.length > 0, "the reason travels with the status");
});

test("an unsolvable series shows its reason rather than a number", () => {
  const view = moneyWeightedView(
    money({ status: "no_solution", annualised_pct: null, period_pct: null, note: "No rate satisfies the cash flows." }),
  );

  assert.equal(view.showFigures, false);
  assert.equal(view.statusLabel, "Not available");
  assert.ok(view.notes.includes("No rate satisfies the cash flows."));
});

test("a short window keeps the period figure and explains the missing annual one", () => {
  const view = moneyWeightedView(
    money({
      annualised_pct: null,
      period_days: 14,
      annualisation_note: "Annualised figure withheld: the window is 14 days.",
    }),
  );

  assert.equal(view.showFigures, true, "the period figure is still shown");
  assert.equal(view.periodLabel, "14-day");
  assert.equal(view.annualisedLabel, null, "no annualised label when it is withheld");
  assert.ok(view.notes.some((note) => note.includes("withheld")));
});

test("a sub-window carries its disclosure", () => {
  const view = moneyWeightedView(money({ disclosure: "Costs paid before the window are not attributed to it." }));

  assert.ok(view.notes.some((note) => note.includes("not attributed")));
});

// --- Suspected corporate actions (M6.2) ---------------------------------------------------

test("the anomaly heading says what is uncertain, and says nothing when there is nothing", () => {
  assert.equal(priceAnomalyHeading(0), null);
  assert.equal(priceAnomalyHeading(-1), null);
  assert.equal(priceAnomalyHeading(1), "1 price move in this window may not be a price move");
  assert.match(priceAnomalyHeading(3), /^3 price moves in this window may not be price moves$/);
});
