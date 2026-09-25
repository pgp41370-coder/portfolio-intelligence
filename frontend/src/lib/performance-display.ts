/** Pure helpers for the performance card: chart geometry, ranges and coverage wording. */

export type ChartPoint = { trade_date: string; value: string };

export type ChartGeometry = {
  line: string;
  area: string;
  min: number;
  max: number;
  first: ChartPoint;
  last: ChartPoint;
};

export type ChartBox = { width: number; height: number; padding: number };

export const RANGES = ["1M", "3M", "6M", "1Y", "MAX"] as const;
export type Range = (typeof RANGES)[number];

const MONTHS_BY_RANGE: Record<Exclude<Range, "MAX">, number> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12 };

/**
 * An SVG path for the value series, plus the closed area beneath it.
 * A flat series is drawn along the vertical middle rather than at the baseline.
 */
export function buildChartGeometry(points: ChartPoint[], box: ChartBox): ChartGeometry | null {
  if (points.length < 2) return null;
  const values = points.map((point) => Number(point.value));
  if (values.some((value) => !Number.isFinite(value))) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const usableWidth = box.width - box.padding * 2;
  const usableHeight = box.height - box.padding * 2;

  const coordinates = values.map((value, index) => {
    const x = box.padding + (usableWidth * index) / (points.length - 1);
    const ratio = span === 0 ? 0.5 : (value - min) / span;
    const y = box.padding + usableHeight * (1 - ratio);
    return `${round(x)},${round(y)}`;
  });

  const line = `M${coordinates.join(" L")}`;
  const baseline = round(box.height - box.padding);
  const area = `${line} L${round(box.width - box.padding)},${baseline} L${round(box.padding)},${baseline} Z`;
  return { line, area, min, max, first: points[0], last: points[points.length - 1] };
}

/** The `start_date` to request for a range, or undefined for the full history. */
export function rangeStart(lastDate: string, range: Range): string | undefined {
  if (range === "MAX") return undefined;
  const end = new Date(`${lastDate}T00:00:00Z`);
  if (Number.isNaN(end.getTime())) return undefined;
  const start = new Date(end);
  start.setUTCMonth(start.getUTCMonth() - MONTHS_BY_RANGE[range]);
  return start.toISOString().slice(0, 10);
}

export type CoverageNotice = { tone: "neutral" | "caution"; text: string };

/** What to tell the reader about gaps. Complete history says nothing; anything else is explicit. */
export function coverageNotice(coverage: {
  status: string;
  sessions_available: number;
  sessions_expected: number;
  missing_session_count: number;
  missing_no_prices_at_all_count?: number;
  missing_some_prices_count?: number;
}): CoverageNotice | null {
  if (coverage.status === "complete") return null;
  if (coverage.status === "insufficient") {
    return {
      tone: "caution",
      text: "Not enough priced sessions to measure performance yet. Prices are collected once a day, so a new portfolio needs a few sessions.",
    };
  }
  const { missing_session_count: missing, sessions_available: available, sessions_expected: expected } = coverage;
  const days = missing === 1 ? "session" : "sessions";
  const sentences = [
    `${available} of ${expected} sessions priced.`,
    `${missing} ${days} had no complete set of closes and ${missing === 1 ? "was" : "were"} left out; returns are not linked across them.`,
  ];
  // A day nothing was priced reads very differently from a day one holding was missed.
  const closed = coverage.missing_no_prices_at_all_count ?? 0;
  const some = coverage.missing_some_prices_count ?? 0;
  if (closed > 0 && some === 0) {
    sentences.push(
      `No holding was priced on ${closed === 1 ? "that session" : "those sessions"}, which usually means the exchange was closed on a day the trading calendar does not list.`,
    );
  } else if (closed > 0) {
    sentences.push(
      `${closed} of them have no price for any holding; the other ${some} ${some === 1 ? "is" : "are"} missing prices for some holdings.`,
    );
  }
  return { tone: "caution", text: sentences.join(" ") };
}

/** How the history was derived, in the reader's language. */
export function basisLabel(basis: string): { label: string; explanation: string } {
  if (basis === "TRANSACTIONS") {
    return {
      label: "Transaction-aware",
      explanation:
        "Built from your recorded transactions, so it follows what was actually held on each session. " +
        "Returns are time-weighted: money you added or withdrew is removed before the return is measured.",
    };
  }
  return {
    label: "Reconstructed",
    explanation:
      "Today's holdings valued at past closing prices. The system stores no transaction history, so this shows how the current basket would have moved, not what was actually held.",
  };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/** One line of a comparison chart, already scaled to the shared box. */
export type ComparisonLine = { line: string; area: string | null; label: string };

export type ComparisonGeometry = {
  portfolio: ComparisonLine;
  benchmark: ComparisonLine | null;
  min: number;
  max: number;
  firstDate: string;
  lastDate: string;
};

type IndexPoint = { trade_date: string; index: number };

/**
 * Portfolio and benchmark on one axis, both as the growth of an index starting at 100.
 *
 * Portfolio value cannot share an axis with a benchmark index - and under the transaction
 * basis, value moves when money is added, which is not performance. The portfolio's own
 * cumulative return (already flow-adjusted by the backend) is what is plotted instead.
 * Only sessions both series priced are drawn; nothing is interpolated across the rest.
 */
export function buildComparisonGeometry(
  portfolioPoints: { trade_date: string; cumulative_return_pct: string }[],
  benchmarkPoints: { trade_date: string; index: string }[],
  box: ChartBox,
): ComparisonGeometry | null {
  const portfolio: IndexPoint[] = portfolioPoints
    .map((point) => ({ trade_date: point.trade_date, index: 100 * (1 + Number(point.cumulative_return_pct) / 100) }))
    .filter((point) => Number.isFinite(point.index));
  if (portfolio.length < 2) return null;

  const benchmarkByDate = new Map(benchmarkPoints.map((point) => [point.trade_date, Number(point.index)]));
  const shared = portfolio.filter((point) => Number.isFinite(benchmarkByDate.get(point.trade_date) ?? NaN));
  const hasBenchmark = shared.length >= 2;

  // Rebase both to the first session they share, so the comparison starts level.
  const base = hasBenchmark ? shared[0] : portfolio[0];
  const rebasedPortfolio = portfolio.map((point) => ({ ...point, index: (point.index / base.index) * 100 }));
  const benchmarkBase = hasBenchmark ? (benchmarkByDate.get(base.trade_date) as number) : 0;
  const rebasedBenchmark = hasBenchmark
    ? shared.map((point) => ({
        trade_date: point.trade_date,
        index: ((benchmarkByDate.get(point.trade_date) as number) / benchmarkBase) * 100,
      }))
    : [];

  const values = [...rebasedPortfolio, ...rebasedBenchmark].map((point) => point.index);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const project = (points: IndexPoint[]) => {
    const span = max - min;
    const usableWidth = box.width - box.padding * 2;
    const usableHeight = box.height - box.padding * 2;
    const total = rebasedPortfolio.length - 1;
    const indexOfDate = new Map(rebasedPortfolio.map((point, position) => [point.trade_date, position]));
    return points.map((point) => {
      const position = indexOfDate.get(point.trade_date) ?? 0;
      const x = box.padding + (usableWidth * position) / (total || 1);
      const ratio = span === 0 ? 0.5 : (point.index - min) / span;
      return `${round(x)},${round(box.padding + usableHeight * (1 - ratio))}`;
    });
  };

  const portfolioCoordinates = project(rebasedPortfolio);
  const line = `M${portfolioCoordinates.join(" L")}`;
  const baseline = box.height - box.padding;
  const firstX = portfolioCoordinates[0].split(",")[0];
  const lastX = portfolioCoordinates[portfolioCoordinates.length - 1].split(",")[0];

  return {
    portfolio: { line, area: `${line} L${lastX},${baseline} L${firstX},${baseline} Z`, label: "Portfolio" },
    benchmark: hasBenchmark
      ? { line: `M${project(rebasedBenchmark).join(" L")}`, area: null, label: "Benchmark" }
      : null,
    min,
    max,
    firstDate: rebasedPortfolio[0].trade_date,
    lastDate: rebasedPortfolio[rebasedPortfolio.length - 1].trade_date,
  };
}

/** Plain wording for a concentration band, with the measure that produced it. */
export function concentrationSummary(band: string | null, effectiveHoldings: string | null): string | null {
  if (!band) return null;
  // Number(null) and Number("") are both 0, which would read as "about 0 positions".
  const effective = effectiveHoldings ? Number(effectiveHoldings) : NaN;
  if (!Number.isFinite(effective) || effective <= 0) return `This portfolio is ${band}.`;
  const rounded = effective.toFixed(1).replace(/\.0$/, "");
  return `This portfolio is ${band}: its weights behave like about ${rounded} equally sized positions.`;
}

/**
 * Split a portfolio's market value into the capital still invested and the gain or loss on it.
 *
 * Percentages are of the larger of the two totals, so the bar always fits and a loss still
 * shows the capital at full width. Returns null when the value is unknown: a missing price must
 * not be drawn as a zero-width gain.
 */
export function capitalVsReturn(
  netInvested: string,
  marketValue: string | null,
): { capitalPct: number; changePct: number; change: string; gain: boolean } | null {
  const capital = Number(netInvested);
  const value = marketValue === null ? NaN : Number(marketValue);
  if (!Number.isFinite(capital) || !Number.isFinite(value) || capital <= 0) return null;
  const change = value - capital;
  const scale = Math.max(capital, value);
  return {
    capitalPct: (Math.min(capital, value) / scale) * 100,
    changePct: (Math.abs(change) / scale) * 100,
    change: change.toFixed(2),
    gain: change >= 0,
  };
}

/**
 * How a portfolio-intelligence response should be presented.
 *
 * The backend decides what is true; this decides what is shown. It exists so the rules — an
 * unavailable explanation shows its reason, a qualified one is badged, a missing figure shows a
 * dash rather than a zero — are testable without rendering React.
 */
export type IntelligenceView = {
  showSections: boolean;
  badge: "qualified" | null;
  emptyReason: string | null;
  limitationCount: number;
  benchmarkLabel: string;
};

export function intelligenceView(intelligence: {
  status: string;
  headline: string;
  returns: unknown | null;
  data_quality: { limitations: string[]; benchmark_status: string; benchmark_basis: string | null };
}): IntelligenceView {
  const unavailable = intelligence.status === "unavailable" || intelligence.returns === null;
  return {
    showSections: !unavailable,
    badge: intelligence.status === "limited" ? "qualified" : null,
    emptyReason: unavailable ? intelligence.headline : null,
    limitationCount: intelligence.data_quality.limitations.length,
    benchmarkLabel:
      intelligence.data_quality.benchmark_status === "available"
        ? intelligence.data_quality.benchmark_basis === "ETF_PROXY"
          ? "Index ETF used as a proxy"
          : "Benchmark"
        : "No benchmark comparison",
  };
}

/** A measured percentage, or a dash — never a zero standing in for "unknown". */
export function measuredOrDash(value: string | null, suffix = "%"): string {
  if (value === null || value === undefined || value === "") return "—";
  return `${value}${suffix}`;
}

/**
 * A contribution in percentage points.
 *
 * Deliberately not formatted with a percent sign: a contribution is measured in percentage
 * points of portfolio return, and "+4.80% pts" reads as a different quantity from "+4.80 pts".
 */
export function formatPoints(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toFixed(2)} pts`;
}

/**
 * How to present a money-weighted return beside a time-weighted one.
 *
 * The two are different measurements, not competing estimates of one thing, so this never
 * ranks them. It decides only what can honestly be shown: a figure, or the reason there is
 * none.
 */
export type MoneyWeightedView = {
  showFigures: boolean;
  periodLabel: string;
  annualisedLabel: string | null;
  statusLabel: string | null;
  notes: string[];
};

export function moneyWeightedView(money: {
  status: string;
  annualised_pct: string | null;
  period_pct: string | null;
  period_days: number;
  annualisation_note: string | null;
  disclosure: string | null;
  note: string;
  roots_found: number;
} | null): MoneyWeightedView | null {
  if (money === null || money.status === "not_applicable") return null;

  const notes: string[] = [];
  if (money.annualisation_note) notes.push(money.annualisation_note);
  if (money.disclosure) notes.push(money.disclosure);

  if (money.status !== "available" || money.period_pct === null) {
    return {
      showFigures: false,
      periodLabel: "—",
      annualisedLabel: null,
      // An ambiguous or unsolvable series shows why, never a number.
      statusLabel:
        money.status === "ambiguous_multiple_roots"
          ? `Not shown: ${money.roots_found} different rates fit these cash flows`
          : "Not available",
      notes: [money.note, ...notes],
    };
  }

  return {
    showFigures: true,
    periodLabel: `${money.period_days}-day`,
    annualisedLabel: money.annualised_pct === null ? null : "Annualised",
    statusLabel: null,
    notes,
  };
}

/**
 * How to present suspected corporate actions.
 *
 * The heading has to carry the point in a few words: these look like price moves and may not
 * be, and nothing has been corrected for them.
 */
export function priceAnomalyHeading(detected: number): string | null {
  if (detected <= 0) return null;
  return detected === 1
    ? "1 price move in this window may not be a price move"
    : `${detected} price moves in this window may not be price moves`;
}
