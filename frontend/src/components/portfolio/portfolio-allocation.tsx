"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { cardStyles } from "@/components/ui/styles";
import {
  describeError,
  getPortfolioAllocation,
  ServiceUnavailableError,
  type PortfolioAllocation as Allocation,
} from "@/lib/api";
import { formatInr } from "@/lib/format";
import { concentrationSummary } from "@/lib/performance-display";
import { formatPercent, formatTradeDate } from "@/lib/valuation-display";

type State =
  | { status: "loading" }
  | { status: "ready"; allocation: Allocation }
  | { status: "unavailable" }
  | { status: "error"; message: string };

type PortfolioAllocationProps = {
  portfolioId: string;
  /** Changing this value reloads allocation, e.g. after a holding is removed. */
  refreshToken: number;
};

export function PortfolioAllocation({ portfolioId, refreshToken }: PortfolioAllocationProps) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let active = true;
    getPortfolioAllocation(portfolioId)
      .then((allocation) => {
        if (active) setState({ status: "ready", allocation });
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
      <AllocationCard>
        <p className="px-5 py-8 text-sm text-ink-subtle sm:px-6">Loading allocation…</p>
      </AllocationCard>
    );
  }

  if (state.status === "unavailable" || state.status === "error") {
    return (
      <AllocationCard>
        <div className="px-5 py-5 sm:px-6">
          <Alert tone="warning" title="Allocation unavailable">
            {state.status === "unavailable"
              ? "Allocation needs the portfolio service, which is not reachable right now."
              : state.message}
          </Alert>
        </div>
      </AllocationCard>
    );
  }

  const { allocation } = state;
  const { concentration, sectors, unpriced_positions: unpriced } = allocation;
  const summary = concentrationSummary(concentration.hhi_band, concentration.effective_holdings);

  return (
    <AllocationCard asOf={allocation.data_as_of}>
      <div className="space-y-5 px-5 py-5 sm:px-6">
        {allocation.holdings.length === 0 ? (
          <p className="rounded-md border border-line bg-canvas px-4 py-6 text-center text-sm text-ink-subtle">
            No holding in this portfolio has a stored closing price, so no weights can be shown.
          </p>
        ) : (
          <>
            <ol className="space-y-2">
              {allocation.holdings.map((holding) => (
                <li key={`${holding.symbol}-${holding.exchange}`} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-x-4 text-sm">
                    <span className="font-medium">{holding.symbol}</span>
                    <span className="tabular-nums text-ink-subtle">
                      {formatInr(holding.market_value)} · {formatPercent(holding.weight_pct)}
                    </span>
                  </div>
                  {/* A bar makes the concentration legible at a glance; the number stays authoritative. */}
                  <div aria-hidden className="h-1.5 overflow-hidden rounded-full bg-canvas">
                    <div
                      className="h-full rounded-full bg-brand/70"
                      style={{ width: `${Math.min(100, Number(holding.weight_pct))}%` }}
                    />
                  </div>
                </li>
              ))}
            </ol>

            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Holdings priced" value={String(concentration.holdings_counted)} />
              <Stat label="Largest position" value={concentration.top_1_pct ? formatPercent(concentration.top_1_pct) : "—"} />
              <Stat label="Top 3" value={concentration.top_3_pct ? formatPercent(concentration.top_3_pct) : "—"} />
              <Stat label="Top 5" value={concentration.top_5_pct ? formatPercent(concentration.top_5_pct) : "—"} />
            </dl>

            {summary && <p className="text-sm text-ink-subtle">{summary}</p>}
          </>
        )}

        {unpriced.length > 0 && (
          <Alert tone="warning" title={`${unpriced.length} holding${unpriced.length === 1 ? "" : "s"} could not be weighted`}>
            {unpriced.map((position) => `${position.symbol} (${position.quantity})`).join(", ")} — no usable closing
            price, so these are left out of the weights rather than shown as zero.
          </Alert>
        )}

        <div className="space-y-1 border-t border-line pt-4 text-xs text-ink-subtle">
          <p>{allocation.note}</p>
          <p>Sector allocation: {sectors.note}</p>
          {allocation.data_as_of && <p>Weights use closing prices dated {formatTradeDate(allocation.data_as_of)}.</p>}
        </div>
      </div>
    </AllocationCard>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-canvas px-4 py-3">
      <dt className="text-xs text-ink-subtle">{label}</dt>
      <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function AllocationCard({ children, asOf }: { children: React.ReactNode; asOf?: string | null }) {
  return (
    <section className={cardStyles}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Allocation</h2>
          {asOf && <span className="text-xs text-ink-subtle">at {formatTradeDate(asOf)} closes</span>}
        </div>
        <DataBadge kind="calculated" />
      </header>
      {children}
    </section>
  );
}
