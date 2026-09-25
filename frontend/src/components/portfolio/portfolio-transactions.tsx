"use client";

import { useCallback, useEffect, useState } from "react";
import { TransactionCsvImport } from "@/components/portfolio/transaction-csv-import";
import { TransactionEntryForm } from "@/components/portfolio/transaction-entry-form";
import { TransactionHistory } from "@/components/portfolio/transaction-history";
import { Alert } from "@/components/ui/alert";
import { DataBadge } from "@/components/ui/data-badge";
import { buttonStyles, cardStyles } from "@/components/ui/styles";
import {
  describeError,
  getPortfolioValuation,
  getTransactions,
  ServiceUnavailableError,
  type Transaction,
} from "@/lib/api";
import { reconcile } from "@/lib/transaction-validation";

type State =
  | { status: "loading" }
  | { status: "ready"; transactions: Transaction[] }
  | { status: "unavailable" }
  | { status: "error"; message: string };

type Tab = "history" | "add" | "import";

const TABS: { id: Tab; label: string }[] = [
  { id: "history", label: "History" },
  { id: "add", label: "Add transaction" },
  { id: "import", label: "Import CSV" },
];

type PortfolioTransactionsProps = {
  portfolioId: string;
  /** The holdings on record, compared against what the ledger implies. */
  holdings: { symbol: string; exchange: string; quantity: number }[];
  /** Called after the ledger changes, so the analytics cards reload. */
  onLedgerChanged: () => void;
};

export function PortfolioTransactions({
  portfolioId,
  holdings,
  onLedgerChanged,
}: PortfolioTransactionsProps) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [tab, setTab] = useState<Tab>("history");
  const [reloadToken, setReloadToken] = useState(0);
  const [latestSession, setLatestSession] = useState<string>();

  // The latest completed NSE session, so the date field can refuse a future trade before the
  // API has to. Failing to load it only removes the hint; the API still rejects one.
  useEffect(() => {
    let active = true;
    getPortfolioValuation(portfolioId)
      .then((valuation) => {
        if (active) setLatestSession(valuation.freshness.expected_session_date);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [portfolioId]);

  useEffect(() => {
    let active = true;
    getTransactions(portfolioId)
      .then((list) => {
        if (active) setState({ status: "ready", transactions: list.transactions });
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
  }, [portfolioId, reloadToken]);

  const handleChanged = useCallback(() => {
    setReloadToken((token) => token + 1);
    onLedgerChanged();
  }, [onLedgerChanged]);

  const count = state.status === "ready" ? state.transactions.length : undefined;

  return (
    <section className={cardStyles}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">Transactions</h2>
          {count !== undefined && (
            <span className="text-xs text-ink-subtle">
              {count} recorded
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Transaction views">
            {TABS.map((option) => (
              <button
                key={option.id}
                type="button"
                role="tab"
                aria-selected={tab === option.id}
                onClick={() => setTab(option.id)}
                className={tab === option.id ? buttonStyles.secondary : buttonStyles.subtle}
              >
                {option.label}
              </button>
            ))}
          </div>
          <DataBadge kind="input" />
        </div>
      </header>

      <div className="px-5 py-5 sm:px-6">
        {state.status === "loading" && <p className="text-sm text-ink-subtle">Loading transactions…</p>}

        {(state.status === "unavailable" || state.status === "error") && (
          <Alert tone="warning" title="Transactions unavailable">
            {state.status === "unavailable"
              ? "The portfolio service is not reachable right now."
              : state.message}
          </Alert>
        )}

        {state.status === "ready" && state.transactions.length > 0 && (
          <Reconciliation transactions={state.transactions} holdings={holdings} />
        )}

        {state.status === "ready" && (
          <>
            {tab === "history" && (
              <TransactionHistory
                portfolioId={portfolioId}
                transactions={state.transactions}
                onChanged={handleChanged}
              />
            )}
            {tab === "add" && (
              <TransactionEntryForm
                portfolioId={portfolioId}
                transactions={state.transactions}
                latestSession={latestSession}
                onSaved={handleChanged}
              />
            )}
            {tab === "import" && (
              <TransactionCsvImport portfolioId={portfolioId} onImported={handleChanged} />
            )}
          </>
        )}
      </div>
    </section>
  );
}

function Reconciliation({
  transactions,
  holdings,
}: {
  transactions: Transaction[];
  holdings: { symbol: string; exchange: string; quantity: number }[];
}) {
  const { reconciled, differences } = reconcile(transactions, holdings);
  if (reconciled) {
    return (
      <div className="mb-4">
        <Alert tone="success" title="Reconciled">
          The ledger&rsquo;s closing position matches the holdings on record.
        </Alert>
      </div>
    );
  }
  return (
    <div className="mb-4">
      <Alert tone="warning" title="Reconciliation required">
        <p>
          The transactions and the holdings on record disagree. Neither is changed automatically:
          performance follows the ledger, while valuation follows the holdings.
        </p>
        <ul className="mt-2 space-y-0.5 tabular-nums">
          {differences.map((difference) => (
            <li key={`${difference.symbol}-${difference.exchange}`}>
              {difference.symbol}: ledger {difference.ledger}, holdings {difference.holdings}
            </li>
          ))}
        </ul>
      </Alert>
    </div>
  );
}
