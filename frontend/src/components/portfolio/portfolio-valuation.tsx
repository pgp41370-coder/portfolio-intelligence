"use client";

import { type ReactNode, useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { cardStyles } from "@/components/ui/styles";
import {
  describeError,
  getPortfolioValuation,
  ServiceUnavailableError,
  type HoldingValuation,
  type PortfolioValuation as Valuation,
  type ValuationStatus,
} from "@/lib/api";
import { formatDateTime, formatInr, formatQuantity } from "@/lib/format";
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
  type Tone,
} from "@/lib/valuation-display";

type State =
  | { status: "loading" }
  | { status: "ready"; valuation: Valuation }
  | { status: "unavailable" }
  | { status: "error"; message: string };

const TONE_TEXT: Record<Tone, string> = {
  positive: "text-positive",
  negative: "text-negative",
  neutral: "text-ink",
};

const STATUS_STYLES: Record<ValuationStatus, string> = {
  VALUED: "border-positive/30 bg-positive-soft text-positive",
  STALE: "border-caution/40 bg-caution-soft text-caution",
  UNPRICED: "border-line-strong bg-canvas text-ink-muted",
};

const FALLBACK_NOTE = "Your holdings and invested capital below are not affected.";

type PortfolioValuationProps = {
  portfolioId: string;
  /** Changing this value reloads the valuation, e.g. after a holding is removed. */
  refreshToken: number;
};

export function PortfolioValuation({ portfolioId, refreshToken }: PortfolioValuationProps) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let active = true;
    getPortfolioValuation(portfolioId)
      .then((valuation) => {
        if (active) setState({ status: "ready", valuation });
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
      <ValuationCard>
        <p className="px-5 py-8 text-sm text-ink-subtle sm:px-6">Loading valuation…</p>
      </ValuationCard>
    );
  }

  if (state.status === "unavailable" || state.status === "error") {
    return (
      <ValuationCard>
        <div className="px-5 py-5 sm:px-6">
          <Alert
            tone={state.status === "error" ? "error" : "warning"}
            title="Valuation unavailable"
          >
            {state.status === "error"
              ? `${state.message} ${FALLBACK_NOTE}`
              : `Market values can't be loaded right now, so no current value, P&L or return is shown. ${FALLBACK_NOTE}`}
          </Alert>
        </div>
      </ValuationCard>
    );
  }

  const { valuation } = state;
  const summary = summarizeValuation(valuation);

  if (summary === "empty") {
    return (
      <ValuationCard>
        <p className="px-5 py-8 text-sm text-ink-subtle sm:px-6">This portfolio has no holdings to value.</p>
      </ValuationCard>
    );
  }

  const { totals, freshness } = valuation;
  const basis = describePriceBasis(valuation);
  const notices = valuationNotices(valuation);
  const sources = [
    ...new Set(valuation.holdings.flatMap((holding) => (holding.price ? [holding.price.source_name] : []))),
  ];
  const priceDate = freshness.latest_price_date
    ? freshness.oldest_price_date && freshness.oldest_price_date !== freshness.latest_price_date
      ? `${formatTradeDate(freshness.oldest_price_date)} – ${formatTradeDate(freshness.latest_price_date)}`
      : formatTradeDate(freshness.latest_price_date)
    : "No prices available";

  return (
    <ValuationCard basis={basis}>
      <dl className="flex flex-col gap-1 border-b border-line px-5 pb-4 text-xs sm:flex-row sm:flex-wrap sm:gap-x-6 sm:px-6">
        <Meta label="Price date" value={priceDate} />
        <Meta label="Data source" value={sources.length > 0 ? sources.join(", ") : "—"} />
        <Meta label="Exchange" value="NSE" />
        <Meta label="Price basis" value="End-of-day close (not a live price)" />
      </dl>

      <dl className="grid grid-cols-1 gap-px bg-line sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Total Invested" value={formatInr(totals.total_invested_value)} />
        <Metric
          label="Current Value"
          value={totals.total_market_value ? formatInr(totals.total_market_value) : null}
          note={
            summary === "partial"
              ? `Priced holdings only: ${formatInr(totals.priced_invested_value)} of ${formatInr(totals.total_invested_value)} invested`
              : undefined
          }
        />
        <Metric
          label="Unrealized P&L"
          value={totals.total_unrealized_pnl ? formatSignedInr(totals.total_unrealized_pnl) : null}
          tone={totals.total_unrealized_pnl ? toneOf(totals.total_unrealized_pnl) : undefined}
        />
        <Metric
          label="Return"
          value={
            totals.total_unrealized_return_pct ? formatSignedPercent(totals.total_unrealized_return_pct) : null
          }
          tone={totals.total_unrealized_return_pct ? toneOf(totals.total_unrealized_return_pct) : undefined}
          note="Unrealized price return; excludes dividends"
        />
      </dl>

      {notices.length > 0 && (
        <div className="space-y-3 border-t border-line px-5 py-4 sm:px-6">
          {notices.map((notice) => (
            <Alert key={notice.title} tone={notice.tone === "warning" ? "warning" : "info"} title={notice.title}>
              {notice.body}
            </Alert>
          ))}
        </div>
      )}

      <div className="relative overflow-x-auto border-t border-line">
        <table className="w-full min-w-[58rem] text-sm">
          <caption className="sr-only">Valuation of each holding at NSE end-of-day closing prices</caption>
          <thead>
            <tr className="border-b border-line text-left align-bottom text-xs uppercase tracking-wide text-ink-subtle">
              <th scope="col" className="py-3 pl-5 pr-3 font-medium sm:pl-6">Symbol</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Qty</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Avg Buy</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">EOD Price</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Value</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">P&amp;L</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Return</th>
              <th scope="col" className="px-3 py-3 text-right font-medium">Weight</th>
              <th scope="col" className="py-3 pl-3 pr-5 font-medium sm:pr-6">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {valuation.holdings.map((holding) => (
              <ValuationRow key={holding.holding_id} holding={holding} />
            ))}
          </tbody>
        </table>
      </div>

      <p className="border-t border-line px-5 py-4 text-xs leading-5 text-ink-subtle sm:px-6">
        {valuation.methodology.note} Calculated {formatDateTime(valuation.valued_at)}.
      </p>
    </ValuationCard>
  );
}

function ValuationCard({ basis, children }: { basis?: string | null; children: ReactNode }) {
  return (
    <section aria-labelledby="valuation-heading" className={`${cardStyles} min-w-0`}>
      <header className="px-5 pb-3 pt-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="valuation-heading" className="text-base font-semibold">
            Portfolio valuation
          </h2>
          <DataBadge kind="market" />
        </div>
        {basis && <p className="mt-1 text-sm text-ink-muted">{basis}</p>}
      </header>
      {children}
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1.5">
      <dt className="text-ink-subtle">{label}:</dt>
      <dd className="font-medium text-ink-muted">{value}</dd>
    </div>
  );
}

function Metric({ label, value, tone, note }: { label: string; value: string | null; tone?: Tone; note?: string }) {
  return (
    <div className="bg-surface px-5 py-4 sm:px-6">
      <dt className="flex items-center gap-2 text-sm text-ink-muted">
        {label}
        <DataBadge kind="calculated" />
      </dt>
      <dd
        className={`mt-1.5 font-mono text-xl font-semibold tabular-nums tracking-tight [overflow-wrap:anywhere] ${
          value === null ? "text-ink-subtle" : TONE_TEXT[tone ?? "neutral"]
        }`}
      >
        {value ?? "Unavailable"}
      </dd>
      {note && <p className="mt-1 text-xs leading-5 text-ink-subtle">{note}</p>}
    </div>
  );
}

function ValuationRow({ holding }: { holding: HoldingValuation }) {
  const pricedElsewhere = holding.price && holding.price.exchange !== holding.exchange;
  return (
    <tr className="align-top">
      <td className="py-3 pl-5 pr-3 sm:pl-6">
        <span className="font-semibold">{holding.symbol}</span>
        <span className="block text-xs text-ink-subtle">
          {holding.exchange}
          {pricedElsewhere ? ` · priced on ${holding.price?.exchange}` : ""}
        </span>
      </td>
      <NumberCell>{formatQuantity(holding.quantity)}</NumberCell>
      <NumberCell>{formatInr(holding.average_buy_price)}</NumberCell>
      <NumberCell>
        {holding.price ? (
          <>
            {formatInr(holding.price.close_price)}
            <span className="block font-sans text-xs text-ink-subtle">{formatTradeDate(holding.price.trade_date)}</span>
          </>
        ) : (
          <Unavailable />
        )}
      </NumberCell>
      <NumberCell>{holding.market_value ? formatInr(holding.market_value) : <Unavailable />}</NumberCell>
      <NumberCell tone={holding.unrealized_pnl ? toneOf(holding.unrealized_pnl) : undefined}>
        {holding.unrealized_pnl ? formatSignedInr(holding.unrealized_pnl) : <Unavailable />}
      </NumberCell>
      <NumberCell tone={holding.unrealized_return_pct ? toneOf(holding.unrealized_return_pct) : undefined}>
        {holding.unrealized_return_pct ? formatSignedPercent(holding.unrealized_return_pct) : <Unavailable />}
      </NumberCell>
      <NumberCell>{holding.weight_pct ? formatPercent(holding.weight_pct) : <Unavailable />}</NumberCell>
      <td className="py-3 pl-3 pr-5 sm:pr-6">
        <span
          title={STATUS_TEXT[holding.status].description}
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[holding.status]}`}
        >
          {STATUS_TEXT[holding.status].label}
        </span>
        {holding.status === "UNPRICED" && (
          <p className="mt-1.5 max-w-[15rem] text-xs leading-5 text-ink-muted">
            {unpricedReasonText(holding.unpriced_reason)}
          </p>
        )}
        {holding.status === "STALE" && (
          <p className="mt-1.5 max-w-[15rem] text-xs leading-5 text-ink-muted">{STATUS_TEXT.STALE.description}</p>
        )}
        {holding.warnings.includes("LARGE_PRICE_MOVE") && (
          <p className="mt-1.5 max-w-[15rem] text-xs leading-5 text-caution">
            Large price move — possible split or bonus issue.
          </p>
        )}
      </td>
    </tr>
  );
}

function NumberCell({ children, tone }: { children: ReactNode; tone?: Tone }) {
  return (
    <td className={`whitespace-nowrap px-3 py-3 text-right font-mono tabular-nums ${tone ? TONE_TEXT[tone] : ""}`}>
      {children}
    </td>
  );
}

function Unavailable() {
  return (
    <span className="text-ink-subtle">
      <span aria-hidden="true">—</span>
      <span className="sr-only">Unavailable</span>
    </span>
  );
}
