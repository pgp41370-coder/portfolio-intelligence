"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { cardStyles } from "@/components/ui/styles";
import {
  describeError,
  getPortfolioPnl,
  ServiceUnavailableError,
  type PortfolioPnl as Pnl,
} from "@/lib/api";
import { formatInr } from "@/lib/format";
import { capitalVsReturn } from "@/lib/performance-display";
import { formatSignedInr, formatTradeDate, toneOf } from "@/lib/valuation-display";

type State =
  | { status: "loading" }
  | { status: "ready"; pnl: Pnl }
  | { status: "unavailable" }
  | { status: "error"; message: string };

const TONE_TEXT = { positive: "text-positive", negative: "text-negative", neutral: "text-ink" } as const;

type PortfolioPnlProps = {
  portfolioId: string;
  /** Changing this value reloads, e.g. after a transaction is added. */
  refreshToken: number;
};

export function PortfolioPnlCard({ portfolioId, refreshToken }: PortfolioPnlProps) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let active = true;
    getPortfolioPnl(portfolioId)
      .then((pnl) => {
        if (active) setState({ status: "ready", pnl });
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
        <p className="px-5 py-8 text-sm text-ink-subtle sm:px-6">Loading profit and loss…</p>
      </Card>
    );
  }

  if (state.status === "unavailable" || state.status === "error") {
    return (
      <Card>
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="warning" title="Profit and loss unavailable">
            {state.status === "unavailable"
              ? "This needs the portfolio service, which is not reachable right now."
              : state.message}
          </Alert>
        </div>
      </Card>
    );
  }

  const { pnl } = state;

  if (!pnl.methodology.available || !pnl.totals) {
    return (
      <Card>
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="info" title="Add transactions to see profit and loss">
            {pnl.methodology.note}
          </Alert>
        </div>
      </Card>
    );
  }

  const { totals } = pnl;
  const split = capitalVsReturn(totals.net_invested, totals.market_value);

  return (
    <Card asOf={pnl.data_as_of}>
      <div className="space-y-5 px-5 py-5 sm:px-6">
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Realised P&L" value={formatSignedInr(totals.realised_pnl)} tone={toneOf(totals.realised_pnl)} hint="Banked by selling" />
          <Metric
            label="Unrealised P&L"
            value={totals.unrealised_pnl ? formatSignedInr(totals.unrealised_pnl) : "—"}
            tone={totals.unrealised_pnl ? toneOf(totals.unrealised_pnl) : "neutral"}
            hint="On positions still held"
          />
          <Metric
            label="Total P&L"
            value={totals.total_pnl ? formatSignedInr(totals.total_pnl) : "—"}
            tone={totals.total_pnl ? toneOf(totals.total_pnl) : "neutral"}
            hint={totals.is_complete ? undefined : "Withheld: a position could not be priced"}
          />
          <Metric label="Costs paid" value={formatInr(totals.fees)} hint="Brokerage, taxes and charges" />
        </dl>

        {/* Capital and performance are different things; showing them on one bar keeps a
            contribution from reading as a gain. */}
        <section className="rounded-md border border-line bg-canvas px-4 py-4">
          <h3 className="text-sm font-semibold">Where the value came from</h3>
          <p className="mt-1 text-xs text-ink-subtle">
            Money you put in is not a return. This splits the portfolio&rsquo;s value into the
            capital still invested and the profit or loss on top of it.
          </p>
          {split ? (
            <div className="mt-3 space-y-2">
              <div aria-hidden className="flex h-3 overflow-hidden rounded-full bg-surface">
                <div className="h-full bg-brand/70" style={{ width: `${split.capitalPct}%` }} />
                <div
                  className={`h-full ${split.gain ? "bg-positive/70" : "bg-negative/70"}`}
                  style={{ width: `${split.changePct}%` }}
                />
              </div>
              <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
                <div className="flex items-center gap-2">
                  <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full bg-brand/70" />
                  <dt className="text-ink-subtle">Net capital invested</dt>
                  <dd className="tabular-nums">{formatInr(totals.net_invested)}</dd>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className={`inline-block h-2.5 w-2.5 rounded-full ${split.gain ? "bg-positive/70" : "bg-negative/70"}`}
                  />
                  <dt className="text-ink-subtle">{split.gain ? "Gain" : "Loss"} on that capital</dt>
                  <dd className={`tabular-nums ${split.gain ? "text-positive" : "text-negative"}`}>
                    {formatSignedInr(split.change)}
                  </dd>
                </div>
                <div className="flex items-center gap-2">
                  <dt className="text-ink-subtle">Market value</dt>
                  <dd className="tabular-nums">{totals.market_value ? formatInr(totals.market_value) : "—"}</dd>
                </div>
              </dl>
            </div>
          ) : (
            <p className="mt-3 text-sm text-ink-subtle">
              A position could not be priced, so the split cannot be shown without guessing.
            </p>
          )}
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
            <Small label="Paid in (contributions)" value={formatInr(totals.contributions)} />
            <Small label="Taken out (withdrawals)" value={formatInr(totals.withdrawals)} />
            <Small label="Cost basis of holdings" value={formatInr(totals.open_cost_basis)} />
          </dl>
        </section>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Profit and loss by security</caption>
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-subtle">
                <th scope="col" className="py-2 pr-3 font-medium">Security</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Qty</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Avg cost</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Market value</th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">Realised</th>
                <th scope="col" className="py-2 text-right font-medium">Unrealised</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {pnl.securities.map((item) => (
                <tr key={`${item.symbol}-${item.exchange}`}>
                  <td className="py-2 pr-3 font-medium">
                    {item.symbol}
                    <span className="ml-1 text-xs text-ink-subtle">{item.exchange}</span>
                    {item.price_note && <p className="text-xs font-normal text-ink-subtle">{item.price_note}</p>}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{item.quantity}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {item.average_cost ? formatInr(item.average_cost) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {item.market_value ? formatInr(item.market_value) : "—"}
                  </td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${TONE_TEXT[toneOf(item.realised_pnl)]}`}>
                    {formatSignedInr(item.realised_pnl)}
                  </td>
                  <td
                    className={`py-2 text-right tabular-nums ${
                      item.unrealised_pnl ? TONE_TEXT[toneOf(item.unrealised_pnl)] : ""
                    }`}
                  >
                    {item.unrealised_pnl ? formatSignedInr(item.unrealised_pnl) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {pnl.unmatched_sales.length > 0 && (
          <Alert tone="warning" title="Some sales could not be matched to a purchase">
            {pnl.unmatched_sales.join("; ")}
          </Alert>
        )}

        <div className="space-y-1 border-t border-line pt-4 text-xs text-ink-subtle">
          <p>Cost basis: {pnl.methodology.cost_basis}. {pnl.methodology.note}</p>
          {pnl.data_as_of && <p>Market values use closing prices dated {formatTradeDate(pnl.data_as_of)}.</p>}
        </div>
      </div>
    </Card>
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

function Card({ children, asOf }: { children: React.ReactNode; asOf?: string | null }) {
  return (
    <section className={cardStyles}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Profit and loss</h2>
          {asOf && <span className="text-xs text-ink-subtle">at {formatTradeDate(asOf)} closes</span>}
        </div>
        <DataBadge kind="calculated" />
      </header>
      {children}
    </section>
  );
}
