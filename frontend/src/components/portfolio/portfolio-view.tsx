"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { InvestedCapitalCard } from "@/components/portfolio/invested-capital-card";
import { PageHeader } from "@/components/portfolio/page-header";
import { ServiceUnavailable } from "@/components/portfolio/service-unavailable";
import { Alert } from "@/components/ui/alert";
import { DataBadge, DataLegend } from "@/components/ui/data-badge";
import { buttonStyles, cardStyles } from "@/components/ui/styles";
import {
  ApiError,
  deleteHolding,
  describeError,
  getPortfolio,
  ServiceUnavailableError,
  type PortfolioDetail,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

type State =
  | { status: "loading" }
  | { status: "ready"; portfolio: PortfolioDetail }
  | { status: "not-found" }
  | { status: "unavailable" }
  | { status: "error"; message: string };

const PORTFOLIOS_CRUMB = { label: "Portfolios", href: "/analyze" };

function stateForError(error: unknown): State {
  if (error instanceof ServiceUnavailableError) return { status: "unavailable" };
  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return { status: "not-found" };
  }
  return { status: "error", message: describeError(error) };
}

type PortfolioViewProps = {
  portfolioId: string;
  justCreated: boolean;
};

export function PortfolioView({ portfolioId, justCreated }: PortfolioViewProps) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [showSaved, setShowSaved] = useState(justCreated);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string>();

  useEffect(() => {
    let active = true;
    getPortfolio(portfolioId)
      .then((portfolio) => {
        if (active) setState({ status: "ready", portfolio });
      })
      .catch((error: unknown) => {
        if (active) setState(stateForError(error));
      });
    return () => {
      active = false;
    };
  }, [portfolioId]);

  async function handleDelete(holdingId: string) {
    setDeletingId(holdingId);
    setActionError(undefined);
    try {
      await deleteHolding(portfolioId, holdingId);
      setState({ status: "ready", portfolio: await getPortfolio(portfolioId) });
      setShowSaved(false);
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setDeletingId(null);
      setConfirmingId(null);
    }
  }

  if (state.status === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader breadcrumbs={[PORTFOLIOS_CRUMB, { label: "Portfolio" }]} title="Portfolio" />
        <p className={`${cardStyles} px-5 py-8 text-sm text-ink-subtle`}>Loading portfolio…</p>
      </div>
    );
  }

  if (state.status !== "ready") {
    return (
      <div className="space-y-6">
        <PageHeader
          breadcrumbs={[PORTFOLIOS_CRUMB, { label: "Portfolio" }]}
          title={state.status === "not-found" ? "Portfolio not found" : "Portfolio"}
          description={
            state.status === "not-found"
              ? "This portfolio does not exist or may have been removed."
              : undefined
          }
        />
        {state.status === "unavailable" && <ServiceUnavailable action="loaded" />}
        {state.status === "error" && (
          <Alert tone="error" title="The portfolio could not be loaded">
            {state.message}
          </Alert>
        )}
        <Link href="/analyze" className={buttonStyles.secondary}>
          Back to portfolios
        </Link>
      </div>
    );
  }

  const { portfolio } = state;
  const rows = portfolio.holdings.map((holding) => ({ ...holding, key: holding.id }));

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[PORTFOLIOS_CRUMB, { label: portfolio.name }]}
        title={portfolio.name}
        description={
          <>
            Created {formatDateTime(portfolio.created_at)} · Last updated{" "}
            {formatDateTime(portfolio.updated_at)}
          </>
        }
        actions={
          <Link href="/analyze" className={buttonStyles.secondary}>
            All portfolios
          </Link>
        }
      />

      {showSaved && (
        <Alert tone="success" title="Portfolio saved">
          Your holdings are stored. Analytics such as allocation, concentration and risk will be
          added in a later release.
        </Alert>
      )}

      <DataLegend />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
        <section className={`${cardStyles} min-w-0`}>
          <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
            <h2 className="text-base font-semibold">
              Holdings{" "}
              <span className="font-normal text-ink-subtle">({portfolio.holdings.length})</span>
            </h2>
            <DataBadge kind="input" />
          </header>
          <HoldingsTable
            rows={rows}
            caption={`Holdings in ${portfolio.name}`}
            emptyMessage="This portfolio has no holdings."
            renderAction={(row) =>
              confirmingId === row.key ? (
                <span className="inline-flex flex-wrap items-center justify-end gap-1">
                  <button
                    type="button"
                    onClick={() => handleDelete(row.key)}
                    disabled={deletingId === row.key}
                    className={buttonStyles.danger}
                  >
                    {deletingId === row.key ? "Removing…" : `Confirm remove`}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmingId(null)}
                    disabled={deletingId === row.key}
                    className={buttonStyles.subtle}
                  >
                    Keep
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmingId(row.key)}
                  className={buttonStyles.danger}
                  aria-label={`Remove ${row.symbol} on ${row.exchange}`}
                >
                  Remove
                </button>
              )
            }
          />
          {actionError && (
            <div className="border-t border-line p-5 sm:px-6">
              <Alert tone="error" title="The holding was not removed">
                {actionError}
              </Alert>
            </div>
          )}
        </section>

        <InvestedCapitalCard
          amount={portfolio.total_invested_capital}
          holdingCount={portfolio.holdings.length}
        />
      </div>
    </div>
  );
}
