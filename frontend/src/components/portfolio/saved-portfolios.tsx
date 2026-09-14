"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ServiceUnavailable } from "@/components/portfolio/service-unavailable";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { cardStyles } from "@/components/ui/styles";
import {
  describeError,
  listPortfolios,
  ServiceUnavailableError,
  type PortfolioSummary,
} from "@/lib/api";
import { formatDateTime, formatInr } from "@/lib/format";

type State =
  | { status: "loading" }
  | { status: "ready"; portfolios: PortfolioSummary[] }
  | { status: "unavailable" }
  | { status: "error"; message: string };

export function SavedPortfolios() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let active = true;
    listPortfolios()
      .then((portfolios) => {
        if (active) setState({ status: "ready", portfolios });
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
  }, []);

  if (state.status === "loading") {
    return <p className={`${cardStyles} px-5 py-8 text-sm text-ink-subtle`}>Loading portfolios…</p>;
  }
  if (state.status === "unavailable") {
    return <ServiceUnavailable action="loaded" />;
  }
  if (state.status === "error") {
    return (
      <Alert tone="error" title="Portfolios could not be loaded">
        {state.message}
      </Alert>
    );
  }
  if (state.portfolios.length === 0) {
    return (
      <p className={`${cardStyles} px-5 py-8 text-center text-sm text-ink-subtle`}>
        No portfolios yet. Create one above to get started.
      </p>
    );
  }

  return (
    <div className={cardStyles}>
      <div className="flex items-center justify-end gap-2 border-b border-line px-5 py-3 text-xs text-ink-subtle">
        Invested capital <DataBadge kind="calculated" />
      </div>
      <ul className="divide-y divide-line">
        {state.portfolios.map((portfolio) => (
          <li key={portfolio.id}>
            <Link
              href={`/portfolios/${portfolio.id}`}
              className="flex flex-col gap-2 px-5 py-4 transition-colors hover:bg-canvas sm:flex-row sm:items-center sm:justify-between sm:gap-6"
            >
              <div className="min-w-0">
                <p className="font-semibold [overflow-wrap:anywhere]">{portfolio.name}</p>
                <p className="mt-1 text-sm text-ink-subtle">
                  {portfolio.holding_count} {portfolio.holding_count === 1 ? "holding" : "holdings"}{" "}
                  · Created {formatDateTime(portfolio.created_at)}
                </p>
              </div>
              <p className="font-mono text-base font-semibold tabular-nums sm:text-right">
                {formatInr(portfolio.total_invested_capital)}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
