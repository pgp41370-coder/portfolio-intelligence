"use client";

import { useEffect, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { buttonStyles, cardStyles } from "@/components/ui/styles";
import {
  describeError,
  getPortfolioPerformance,
  ServiceUnavailableError,
  type PortfolioPerformance as Performance,
} from "@/lib/api";
import { formatInr } from "@/lib/format";
import {
  RANGES,
  basisLabel,
  buildChartGeometry,
  buildComparisonGeometry,
  coverageNotice,
  rangeStart,
  type Range,
} from "@/lib/performance-display";
import { formatPercent, formatSignedPercent, formatTradeDate, toneOf } from "@/lib/valuation-display";

const CHART = { width: 640, height: 160, padding: 8 };
const BENCHMARK_KEY = "NIFTY50";

const TONE_TEXT = {
  positive: "text-positive",
  negative: "text-negative",
  neutral: "text-ink",
} as const;

type State =
  | { status: "loading" }
  | { status: "ready"; performance: Performance }
  | { status: "unavailable" }
  | { status: "error"; message: string };

type PortfolioPerformanceProps = {
  portfolioId: string;
  /** Changing this value reloads performance, e.g. after a holding is removed. */
  refreshToken: number;
};

export function PortfolioPerformance({ portfolioId, refreshToken }: PortfolioPerformanceProps) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [range, setRange] = useState<Range>("MAX");
  const lastSession = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    const startDate = range === "MAX" ? undefined : rangeStart(lastSession.current ?? "", range);
    // The previous range stays on screen until the new one resolves, which avoids a flicker.
    getPortfolioPerformance(portfolioId, { startDate, benchmark: BENCHMARK_KEY })
      .then((performance) => {
        if (!active) return;
        if (range === "MAX" && performance.period.end) lastSession.current = performance.period.end;
        setState({ status: "ready", performance });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState(
          error instanceof ServiceUnavailableError
            ? { status: "unavailable" }
            : { status: "error", message: describeError(error) },
        );
      });
    return () => {
      active = false;
    };
  }, [portfolioId, refreshToken, range]);

  if (state.status === "loading") {
    return (
      <PerformanceCard range={range} onRange={setRange}>
        <p className="px-5 py-8 text-sm text-ink-subtle sm:px-6">Loading performance…</p>
      </PerformanceCard>
    );
  }

  if (state.status === "unavailable" || state.status === "error") {
    return (
      <PerformanceCard range={range} onRange={setRange}>
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="warning" title="Performance unavailable">
            {state.status === "unavailable"
              ? "Historical performance needs the portfolio service, which is not reachable right now."
              : state.message}
          </Alert>
        </div>
      </PerformanceCard>
    );
  }

  const { performance } = state;
  const { summary, coverage, benchmark, series, risk, reconciliation } = performance;
  const basis = basisLabel(performance.basis);
  const notice = coverageNotice(coverage);
  const cumulative = summary.cumulative_return_pct;
  // With a benchmark to compare against, both lines are drawn as the growth of an index from
  // 100; on its own, the portfolio's rupee value is the more useful axis.
  const comparison = benchmark.status === "available" ? buildComparisonGeometry(series, benchmark.series, CHART) : null;
  const geometry = comparison ? null : buildChartGeometry(series, CHART);

  return (
    <PerformanceCard range={range} onRange={setRange} basisLabel={basis.label}>
      <div className="space-y-5 px-5 py-5 sm:px-6">
        <p className="text-sm text-ink-subtle">{basis.explanation}</p>

        {reconciliation.status === "differs" && (
          <Alert tone="warning" title="Transactions and holdings disagree">
            <p>{reconciliation.note}</p>
            <ul className="mt-2 space-y-0.5">
              {reconciliation.differences.map((difference) => (
                <li key={`${difference.symbol}-${difference.exchange}`} className="tabular-nums">
                  {difference.symbol}: ledger {difference.ledger_quantity}, holdings {difference.holdings_quantity}
                </li>
              ))}
            </ul>
          </Alert>
        )}

        {notice && (
          <Alert tone="warning" title={coverage.status === "insufficient" ? "Not enough history yet" : "Incomplete history"}>
            {notice.text}
          </Alert>
        )}

        {comparison ? (
          <figure className="space-y-2">
            <svg
              viewBox={`0 0 ${CHART.width} ${CHART.height}`}
              preserveAspectRatio="none"
              className="h-40 w-full text-brand"
              role="img"
              aria-label={`Portfolio and benchmark growth from ${formatTradeDate(comparison.firstDate)} to ${formatTradeDate(comparison.lastDate)}, both starting at 100`}
            >
              <path d={comparison.portfolio.area ?? ""} fill="currentColor" fillOpacity="0.1" />
              <path
                d={comparison.portfolio.line}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
              {comparison.benchmark && (
                <path
                  d={comparison.benchmark.line}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeDasharray="4 3"
                  strokeOpacity="0.55"
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </svg>
            <figcaption className="space-y-1 text-xs text-ink-subtle">
              <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="inline-flex items-center gap-1.5">
                  <span aria-hidden className="inline-block h-0.5 w-4 bg-brand" />
                  This portfolio
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span aria-hidden className="inline-block h-0 w-4 border-t-2 border-dashed border-brand/60" />
                  {benchmark.display_name}
                </span>
              </span>
              <span className="flex justify-between gap-x-4">
                <span>{formatTradeDate(comparison.firstDate)}</span>
                <span>Growth of 100, rebased where both series start</span>
                <span>{formatTradeDate(comparison.lastDate)}</span>
              </span>
            </figcaption>
          </figure>
        ) : geometry ? (
          <figure className="space-y-2">
            <svg
              viewBox={`0 0 ${CHART.width} ${CHART.height}`}
              preserveAspectRatio="none"
              className="h-40 w-full text-brand"
              role="img"
              aria-label={`Portfolio value from ${formatTradeDate(geometry.first.trade_date)} to ${formatTradeDate(geometry.last.trade_date)}`}
            >
              <path d={geometry.area} fill="currentColor" fillOpacity="0.1" />
              <path d={geometry.line} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            </svg>
            {/* The dates stay on one row at every width; the value range drops below them when space runs out. */}
            <figcaption className="space-y-1 text-xs text-ink-subtle sm:flex sm:items-baseline sm:justify-between sm:gap-x-4 sm:space-y-0">
              <span className="flex justify-between gap-x-4 sm:contents">
                <span className="sm:order-1">{formatTradeDate(geometry.first.trade_date)}</span>
                <span className="sm:order-3">{formatTradeDate(geometry.last.trade_date)}</span>
              </span>
              <span className="block text-center sm:order-2 sm:text-left">
                {formatInr(String(geometry.min))} – {formatInr(String(geometry.max))}
              </span>
            </figcaption>
          </figure>
        ) : (
          <p className="rounded-md border border-line bg-canvas px-4 py-6 text-center text-sm text-ink-subtle">
            A chart appears once at least two sessions are fully priced.
          </p>
        )}

        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Cumulative return" value={cumulative ? formatSignedPercent(cumulative) : "—"} tone={cumulative ? toneOf(cumulative) : "neutral"} />
          <Metric
            label="Volatility (annualised)"
            value={summary.volatility_pct ? formatPercent(summary.volatility_pct) : "—"}
            hint={summary.volatility_note ?? undefined}
          />
          <Metric
            label="Max drawdown"
            value={summary.max_drawdown_pct ? formatPercent(summary.max_drawdown_pct) : "—"}
            tone={summary.max_drawdown_pct && Number(summary.max_drawdown_pct) < 0 ? "negative" : "neutral"}
          />
          <Metric
            label={benchmark.status === "available" ? `vs ${benchmark.tracks ?? "benchmark"}` : "vs benchmark"}
            value={benchmark.excess_return_pct ? formatSignedPercent(benchmark.excess_return_pct) : "—"}
            tone={benchmark.excess_return_pct ? toneOf(benchmark.excess_return_pct) : "neutral"}
            hint={
              benchmark.status === "available"
                ? `${benchmark.display_name} returned ${
                    benchmark.cumulative_return_pct ? formatSignedPercent(benchmark.cumulative_return_pct) : "—"
                  } over the same ${benchmark.sessions_compared} sessions.`
                : "No benchmark comparison is available."
            }
          />
        </dl>

        <RiskTable risk={risk} />

        <div className="space-y-1 border-t border-line pt-4 text-xs text-ink-subtle">
          <p>
            {coverage.sessions_available} of {coverage.sessions_expected} sessions priced
            {summary.returns_used > 0 && `; ${summary.returns_used} daily returns used`}
            {summary.returns_skipped_across_gaps > 0 &&
              `; ${summary.returns_skipped_across_gaps} skipped across gaps`}
            .
          </p>
          {/* Coverage can be complete and still end before today; say so rather than letting
              the window quietly stop at the last price. */}
          {coverage.sessions_behind_latest > 0 && (
            <p>
              This history ends at the newest stored close and is {coverage.sessions_behind_latest} session
              {coverage.sessions_behind_latest === 1 ? "" : "s"} behind the latest completed NSE session
              {coverage.latest_expected_session ? ` (${formatTradeDate(coverage.latest_expected_session)})` : ""}.
            </p>
          )}
          <p>
            {benchmark.status === "available" && benchmark.cumulative_return_pct
              ? `Versus ${benchmark.display_name}: ${formatSignedPercent(benchmark.cumulative_return_pct)}${
                  benchmark.excess_return_pct ? ` (excess ${formatSignedPercent(benchmark.excess_return_pct)})` : ""
                }, over ${benchmark.sessions_compared} shared sessions. ${benchmark.note}`
              : `Benchmark comparison unavailable. ${benchmark.note}`}
          </p>
          {summary.net_external_flow && (
            <p>
              Net invested over this window: {formatInr(summary.net_external_flow)}
              {summary.returns_skipped_zero_base > 0 &&
                `; ${summary.returns_skipped_zero_base} session(s) held nothing and carry no return`}
              .
            </p>
          )}
          <p>{performance.methodology.note}</p>
          <p>Sharpe ratio: {performance.methodology.sharpe}</p>
          {performance.excluded_holdings.length > 0 && (
            <p>
              Excluded from this chart:{" "}
              {performance.excluded_holdings.map((holding) => holding.symbol).join(", ")} — no usable NSE price history.
            </p>
          )}
        </div>
      </div>
    </PerformanceCard>
  );
}

function RiskTable({ risk }: { risk: Performance["risk"] }) {
  const rows: { label: string; measure: Performance["risk"]["beta"]; suffix?: string }[] = [
    { label: "Downside volatility (annualised)", measure: risk.downside_volatility, suffix: "%" },
    { label: "Beta vs benchmark", measure: risk.beta },
    { label: "Tracking error (annualised)", measure: risk.tracking_error_pct, suffix: "%" },
    { label: "Information ratio", measure: risk.information_ratio },
    { label: "Sharpe ratio", measure: risk.sharpe_ratio },
  ];
  return (
    <div className="rounded-md border border-line bg-canvas">
      <h3 className="border-b border-line px-4 py-2.5 text-sm font-semibold">Risk measures</h3>
      <dl className="divide-y divide-line">
        {rows.map((row) => (
          <div key={row.label} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2.5">
            <dt className="text-sm text-ink-subtle">{row.label}</dt>
            <dd className="text-sm tabular-nums">
              {row.measure.available && row.measure.value !== null ? (
                <span className="font-semibold">
                  {Number(row.measure.value).toFixed(2)}
                  {row.suffix ?? ""}
                </span>
              ) : (
                /* Withheld, with the reason: never a zero standing in for "unknown". */
                <span className="text-ink-subtle">Not available</span>
              )}
            </dd>
            {!row.measure.available && row.measure.note && (
              <p className="w-full text-xs text-ink-subtle">{row.measure.note}</p>
            )}
          </div>
        ))}
      </dl>
      <p className="border-t border-line px-4 py-2.5 text-xs text-ink-subtle">
        {risk.note} Measured from {risk.observations} daily return{risk.observations === 1 ? "" : "s"}.
      </p>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: string;
  tone?: keyof typeof TONE_TEXT;
  hint?: string;
}) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-canvas px-4 py-3">
      <dt className="text-xs text-ink-subtle">{label}</dt>
      <dd className={`mt-1 text-lg font-semibold tabular-nums ${TONE_TEXT[tone]}`}>{value}</dd>
      {hint && <p className="mt-1 text-xs text-ink-subtle">{hint}</p>}
    </div>
  );
}

function PerformanceCard({
  children,
  range,
  onRange,
  basisLabel: basis,
}: {
  children: React.ReactNode;
  range: Range;
  onRange: (next: Range) => void;
  basisLabel?: string;
}) {
  return (
    <section className={cardStyles}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Performance</h2>
          {basis && (
            <span className="inline-flex shrink-0 items-center rounded-full border border-caution/40 bg-caution-soft px-2 py-0.5 text-xs font-medium text-caution">
              {basis}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1" role="group" aria-label="Date range">
            {RANGES.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onRange(option)}
                aria-pressed={range === option}
                className={range === option ? buttonStyles.secondary : buttonStyles.subtle}
              >
                {option}
              </button>
            ))}
          </div>
          <DataBadge kind="calculated" />
        </div>
      </header>
      {children}
    </section>
  );
}
