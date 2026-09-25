"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { cardStyles } from "@/components/ui/styles";
import {
  describeError,
  getPortfolioTimeline,
  ServiceUnavailableError,
  type PortfolioTimeline as Timeline,
} from "@/lib/api";
import { formatInr } from "@/lib/format";
import { formatSignedPercent, formatTradeDate, toneOf } from "@/lib/valuation-display";

type State =
  | { status: "loading" }
  | { status: "ready"; timeline: Timeline }
  | { status: "unavailable" }
  | { status: "error"; message: string };

type PortfolioTimelineProps = {
  portfolioId: string;
  refreshToken: number;
};

export function PortfolioTimelineCard({ portfolioId, refreshToken }: PortfolioTimelineProps) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let active = true;
    getPortfolioTimeline(portfolioId)
      .then((timeline) => {
        if (active) setState({ status: "ready", timeline });
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
        <p className="px-5 py-8 text-sm text-ink-subtle sm:px-6">Loading timeline…</p>
      </Card>
    );
  }

  if (state.status === "unavailable" || state.status === "error") {
    return (
      <Card>
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="warning" title="Timeline unavailable">
            {state.status === "unavailable"
              ? "The timeline needs the portfolio service, which is not reachable right now."
              : state.message}
          </Alert>
        </div>
      </Card>
    );
  }

  const { timeline } = state;

  if (timeline.entries.length === 0) {
    return (
      <Card>
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="info" title="Nothing to show yet">
            {timeline.note}
          </Alert>
        </div>
      </Card>
    );
  }

  return (
    <Card count={timeline.transaction_count}>
      <div className="space-y-4 px-5 py-5 sm:px-6">
        <ol className="space-y-3">
          {timeline.entries.map((entry) => (
            <li key={entry.trade_date} className="rounded-md border border-line bg-canvas px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="text-sm font-semibold">{formatTradeDate(entry.trade_date)}</p>
                {entry.daily_return_pct && (
                  <p className={`text-sm tabular-nums ${toneOf(entry.daily_return_pct) === "positive" ? "text-positive" : toneOf(entry.daily_return_pct) === "negative" ? "text-negative" : "text-ink"}`}>
                    {formatSignedPercent(entry.daily_return_pct)} that session
                  </p>
                )}
              </div>

              <ul className="mt-2 space-y-1 text-sm">
                {entry.transactions.map((item, index) => (
                  <li key={`${item.symbol}-${index}`} className="flex flex-wrap items-baseline gap-x-2">
                    <span
                      className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
                        item.kind === "BUY"
                          ? "border-positive/40 bg-positive-soft text-positive"
                          : "border-caution/40 bg-caution-soft text-caution"
                      }`}
                    >
                      {item.kind === "BUY" ? "Buy" : "Sell"}
                    </span>
                    <span className="font-medium">{item.symbol}</span>
                    <span className="tabular-nums text-ink-subtle">
                      {item.quantity} × {formatInr(item.price)} = {formatInr(item.gross_value)}
                    </span>
                    {item.trade_date !== entry.trade_date && (
                      <span className="text-xs text-ink-subtle">
                        (entered as {formatTradeDate(item.trade_date)}, a non-trading day)
                      </span>
                    )}
                  </li>
                ))}
              </ul>

              <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-subtle">
                <div className="flex gap-1.5">
                  <dt>Position</dt>
                  <dd className="tabular-nums text-ink">{entry.position_changes.join(", ")}</dd>
                </div>
                {entry.portfolio_value && (
                  <div className="flex gap-1.5">
                    <dt>Portfolio value</dt>
                    <dd className="tabular-nums text-ink">{formatInr(entry.portfolio_value)}</dd>
                  </div>
                )}
                {entry.cumulative_return_pct && (
                  <div className="flex gap-1.5">
                    <dt>Return to date</dt>
                    <dd className="tabular-nums text-ink">{formatSignedPercent(entry.cumulative_return_pct)}</dd>
                  </div>
                )}
              </dl>
            </li>
          ))}
        </ol>

        <p className="border-t border-line pt-4 text-xs text-ink-subtle">{timeline.note}</p>
      </div>
    </Card>
  );
}

function Card({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <section className={cardStyles}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Timeline</h2>
          {count !== undefined && (
            <span className="text-xs text-ink-subtle">
              {count} transaction{count === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <DataBadge kind="input" />
      </header>
      {children}
    </section>
  );
}
