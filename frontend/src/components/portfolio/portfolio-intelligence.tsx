"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { cardStyles } from "@/components/ui/styles";
import {
  describeError,
  getPortfolioIntelligence,
  ServiceUnavailableError,
  type Contributor,
  type PortfolioIntelligence as Intelligence,
} from "@/lib/api";
import { formatPoints, moneyWeightedView, priceAnomalyHeading } from "@/lib/performance-display";
import { formatPercent, formatSignedInr, formatSignedPercent, formatTradeDate, toneOf } from "@/lib/valuation-display";

const BENCHMARK_KEY = "NIFTY50";

const TONE_TEXT = { positive: "text-positive", negative: "text-negative", neutral: "text-ink" } as const;

type State =
  | { status: "loading" }
  | { status: "ready"; intelligence: Intelligence }
  | { status: "unavailable" }
  | { status: "error"; message: string };

type PortfolioIntelligenceProps = {
  portfolioId: string;
  /** Changing this value reloads, e.g. after a transaction is added. */
  refreshToken: number;
};

export function PortfolioIntelligenceCard({ portfolioId, refreshToken }: PortfolioIntelligenceProps) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let active = true;
    getPortfolioIntelligence(portfolioId, { benchmark: BENCHMARK_KEY })
      .then((intelligence) => {
        if (active) setState({ status: "ready", intelligence });
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
  }, [portfolioId, refreshToken]);

  if (state.status === "loading") {
    return (
      <Card>
        <p className="px-5 py-8 text-sm text-ink-subtle sm:px-6">Loading portfolio intelligence…</p>
      </Card>
    );
  }

  if (state.status === "unavailable" || state.status === "error") {
    return (
      <Card>
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="warning" title="Portfolio intelligence unavailable">
            {state.status === "unavailable"
              ? "This needs the portfolio service, which is not reachable right now."
              : state.message}
          </Alert>
        </div>
      </Card>
    );
  }

  const { intelligence } = state;
  const { returns, cash_flow: cashFlow, risk, data_quality: quality } = intelligence;
  const money = moneyWeightedView(intelligence.money_weighted);

  if (intelligence.status === "unavailable" || !returns) {
    return (
      <Card period={intelligence.period}>
        <div className="space-y-4 px-5 py-5 sm:px-6">
          <Alert tone="info" title="Nothing to explain yet">
            {intelligence.headline}
          </Alert>
          <DataQuality quality={quality} />
        </div>
      </Card>
    );
  }

  return (
    <Card period={intelligence.period} limited={intelligence.status === "limited"}>
      <div className="space-y-6 px-5 py-5 sm:px-6">
        <p className="text-sm leading-6">{intelligence.headline}</p>

        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Metric
            label="Portfolio return"
            value={returns.portfolio_return_pct ? formatSignedPercent(returns.portfolio_return_pct) : "—"}
            tone={returns.portfolio_return_pct ? toneOf(returns.portfolio_return_pct) : "neutral"}
            hint={returns.calculation_method === "TWR_DAILY_CHAINED" ? "Time-weighted" : "Price return"}
          />
          <Metric
            label="Benchmark proxy"
            value={returns.benchmark_return_pct ? formatSignedPercent(returns.benchmark_return_pct) : "—"}
            tone={returns.benchmark_return_pct ? toneOf(returns.benchmark_return_pct) : "neutral"}
            hint={quality.benchmark_basis === "ETF_PROXY" ? "Index ETF used as a proxy" : undefined}
          />
          <Metric
            label="Relative"
            value={returns.relative_return_pct ? formatSignedPercent(returns.relative_return_pct) : "—"}
            tone={returns.relative_return_pct ? toneOf(returns.relative_return_pct) : "neutral"}
            hint="Percentage points versus the proxy"
          />
        </dl>

        {money && (
          <Section title="Two returns, two questions">
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Metric
                label="Time-weighted return"
                value={returns.portfolio_return_pct ? formatSignedPercent(returns.portfolio_return_pct) : "—"}
                tone={returns.portfolio_return_pct ? toneOf(returns.portfolio_return_pct) : "neutral"}
                hint="How the portfolio performed, with cash flows removed"
              />
              <Metric
                label={`Money-weighted return (${money.periodLabel})`}
                value={
                  money.showFigures && intelligence.money_weighted?.period_pct
                    ? formatSignedPercent(intelligence.money_weighted.period_pct)
                    : "—"
                }
                tone={
                  money.showFigures && intelligence.money_weighted?.period_pct
                    ? toneOf(intelligence.money_weighted.period_pct)
                    : "neutral"
                }
                hint="What the money actually earned, including when it was added or taken out"
              />
              <Metric
                label="Money-weighted, annualised"
                value={
                  money.annualisedLabel && intelligence.money_weighted?.annualised_pct
                    ? formatSignedPercent(intelligence.money_weighted.annualised_pct)
                    : "—"
                }
                tone={
                  intelligence.money_weighted?.annualised_pct
                    ? toneOf(intelligence.money_weighted.annualised_pct)
                    : "neutral"
                }
                hint={money.annualisedLabel ? "The same rate stated per year" : "Withheld for this window"}
              />
            </dl>
            {money.statusLabel && (
              <p className="mt-3 text-sm text-ink-subtle">{money.statusLabel}</p>
            )}
            <p className="mt-3 text-xs text-ink-subtle">
              These answer different questions and neither replaces the other. The time-weighted
              return measures the portfolio with the effect of deposits and withdrawals removed,
              which is what a benchmark can be compared against. The money-weighted return measures
              the money, including the timing and size of those flows.
            </p>
            {money.notes.map((note) => (
              <p key={note} className="mt-2 text-xs text-ink-subtle">
                {note}
              </p>
            ))}
          </Section>
        )}

        {intelligence.findings.length > 0 && (
          <Section title="What the numbers say">
            <ul className="space-y-1.5 text-sm leading-6">
              {intelligence.findings.map((finding) => (
                <li key={finding} className="flex gap-2">
                  <span aria-hidden className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-subtle" />
                  <span>{finding}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="What drove the return">
          {returns.top_positive.length === 0 && returns.top_negative.length === 0 ? (
            <p className="text-sm text-ink-subtle">No security moved the portfolio over this window.</p>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Contributors title="Added to the return" rows={returns.top_positive} tone="positive" />
              <Contributors title="Subtracted from the return" rows={returns.top_negative} tone="negative" />
            </div>
          )}
          <p className="mt-2 text-xs text-ink-subtle">
            <span className="font-medium">Its price</span> is how far the security moved.{" "}
            <span className="font-medium">Points</span> is what that did to this portfolio, which
            also depends on how much of it was held and how large the portfolio was at the time —
            so the two can differ, and can even have opposite signs.
          </p>
          <p className="mt-3 text-xs text-ink-subtle">
            Contributions sum to {returns.sum_of_contributions_pct ?? "—"}
            {returns.compounding_difference_pct &&
              `, which differs from the compounded ${returns.portfolio_return_pct ?? "—"} by ${returns.compounding_difference_pct} percentage points of compounding`}
            . {returns.note}
          </p>
        </Section>

        {cashFlow && (
          <Section title="Return versus value change">
            <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
              <Small label="Portfolio value change" value={cashFlow.value_change ? formatSignedInr(cashFlow.value_change) : "—"} />
              <Small
                label="Net cash flow"
                value={cashFlow.net_external_flow ? formatSignedInr(cashFlow.net_external_flow) : "—"}
              />
              <Small
                label="Change from performance"
                value={cashFlow.return_driven_change ? formatSignedInr(cashFlow.return_driven_change) : "—"}
              />
              <Small label="Time-weighted return" value={cashFlow.twr_pct ? formatSignedPercent(cashFlow.twr_pct) : "—"} />
            </dl>
            <p className="mt-3 text-xs text-ink-subtle">{cashFlow.note}</p>
          </Section>
        )}

        {risk && (
          <Section title="Risk context">
            <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
              <Small label="Volatility" value={risk.volatility_pct ? formatPercent(risk.volatility_pct) : "Not available"} />
              <Small label="Max drawdown" value={risk.max_drawdown_pct ? formatPercent(risk.max_drawdown_pct) : "—"} />
              <Small
                label="Current drawdown"
                value={risk.current_drawdown_pct ? formatPercent(risk.current_drawdown_pct) : "—"}
              />
              <Small
                label="Largest position"
                value={
                  risk.largest_position_symbol && risk.largest_position_weight_pct
                    ? `${risk.largest_position_symbol} · ${formatPercent(risk.largest_position_weight_pct)}`
                    : "—"
                }
              />
            </dl>
            <p className="mt-3 text-xs text-ink-subtle">
              {risk.positive_sessions} sessions gained, {risk.negative_sessions} lost, {risk.flat_sessions} unchanged.
              {risk.concentration_band && ` Concentration measures as ${risk.concentration_band}.`} {risk.note}
            </p>
          </Section>
        )}

        <DataQuality quality={quality} />

        <p className="border-t border-line pt-4 text-xs text-ink-subtle">{intelligence.methodology}</p>
      </div>
    </Card>
  );
}

function Contributors({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: Contributor[];
  tone: "positive" | "negative";
}) {
  if (rows.length === 0) {
    return (
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{title}</h4>
        <p className="mt-2 text-sm text-ink-subtle">None over this window.</p>
      </div>
    );
  }
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{title}</h4>
      <ol className="mt-2 space-y-1.5">
        {rows.map((row) => (
          <li key={`${row.symbol}-${row.exchange}`} className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
            <span>
              <span className="text-ink-subtle">{row.rank}.</span> <span className="font-medium">{row.symbol}</span>
              {row.security_return_pct && (
                <span className="ml-2 text-xs text-ink-subtle">
                  {/* The leading space keeps the two readable when the markup is flattened. */}
                  {" "}its price {formatSignedPercent(row.security_return_pct)}
                </span>
              )}
            </span>
            <span className={`tabular-nums font-semibold ${TONE_TEXT[tone]}`}>
              {formatPoints(row.contribution_pct)}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function DataQuality({ quality }: { quality: Intelligence["data_quality"] }) {
  const anomalies = quality.price_anomalies;
  return (
    <Section title="Data quality">
      {anomalies && anomalies.detected > 0 && (
        <div className="mb-4">
          <Alert
            tone="warning"
            title={priceAnomalyHeading(anomalies.detected) ?? ""}
          >
            <p>{anomalies.note}</p>
            <ul className="mt-2 space-y-1">
              {anomalies.anomalies.map((anomaly) => (
                <li key={`${anomaly.symbol}-${anomaly.trade_date}`}>{anomaly.description}</li>
              ))}
            </ul>
          </Alert>
        </div>
      )}
      <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <Small label="Coverage" value={`${quality.sessions_available} of ${quality.sessions_expected} sessions`} />
        <Small
          label="Behind latest session"
          value={quality.sessions_behind_latest === 0 ? "Current" : `${quality.sessions_behind_latest} sessions`}
        />
        <Small label="Benchmark" value={quality.benchmark_status.replace(/_/g, " ")} />
        <Small label="Ledger vs holdings" value={quality.reconciliation_status.replace(/_/g, " ")} />
      </dl>
      {quality.limitations.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-ink-subtle">
          {quality.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-ink-subtle">{quality.note}</p>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="border-b border-line pb-2 text-sm font-semibold">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
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

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-xs text-ink-subtle">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}

function Card({
  children,
  period,
  limited,
}: {
  children: React.ReactNode;
  period?: { start: string | null; end: string | null };
  limited?: boolean;
}) {
  return (
    <section className={cardStyles}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Portfolio intelligence</h2>
          {period?.start && period.end && (
            <span className="text-xs text-ink-subtle">
              {formatTradeDate(period.start)} – {formatTradeDate(period.end)}
            </span>
          )}
          {limited && (
            <span className="inline-flex shrink-0 items-center rounded-full border border-caution/40 bg-caution-soft px-2 py-0.5 text-xs font-medium text-caution">
              Qualified
            </span>
          )}
        </div>
        <DataBadge kind="calculated" />
      </header>
      {children}
    </section>
  );
}
