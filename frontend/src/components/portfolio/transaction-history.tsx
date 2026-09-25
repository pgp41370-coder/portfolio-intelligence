"use client";

import { useMemo, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { buttonStyles, inputStyles } from "@/components/ui/styles";
import { deleteTransaction, describeError, ServiceUnavailableError, type Transaction } from "@/lib/api";
import { formatInr } from "@/lib/format";
import { grossValue } from "@/lib/transaction-validation";
import { formatTradeDate } from "@/lib/valuation-display";

type Filters = { kind: "ALL" | "BUY" | "SELL"; symbol: string; from: string; to: string };

const EMPTY_FILTERS: Filters = { kind: "ALL", symbol: "", from: "", to: "" };

type TransactionHistoryProps = {
  portfolioId: string;
  transactions: Transaction[];
  onChanged: () => void;
};

export function TransactionHistory({ portfolioId, transactions, onChanged }: TransactionHistoryProps) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [removing, setRemoving] = useState<string>();
  const [error, setError] = useState<string>();

  const symbols = useMemo(
    () => [...new Set(transactions.map((item) => item.symbol))].sort(),
    [transactions],
  );

  const visible = useMemo(() => {
    const symbol = filters.symbol.trim().toUpperCase();
    return transactions
      .filter((item) => (filters.kind === "ALL" ? true : item.kind === filters.kind))
      .filter((item) => (symbol ? item.symbol === symbol : true))
      .filter((item) => (filters.from ? item.trade_date >= filters.from : true))
      .filter((item) => (filters.to ? item.trade_date <= filters.to : true))
      .slice()
      .sort((a, b) => (a.trade_date === b.trade_date ? b.created_at.localeCompare(a.created_at) : b.trade_date.localeCompare(a.trade_date)));
  }, [transactions, filters]);

  async function handleDelete(id: string) {
    if (removing) return;
    setRemoving(id);
    setError(undefined);
    try {
      await deleteTransaction(portfolioId, id);
      onChanged();
    } catch (caught: unknown) {
      setError(
        caught instanceof ServiceUnavailableError
          ? "The portfolio service is not reachable right now. Nothing was removed."
          : describeError(caught),
      );
    } finally {
      setRemoving(undefined);
    }
  }

  if (transactions.length === 0) {
    return (
      <p className="rounded-md border border-line bg-canvas px-4 py-6 text-center text-sm text-ink-subtle">
        No transactions recorded yet. Add one above, or import a CSV, and this portfolio&rsquo;s
        history becomes transaction-aware.
      </p>
    );
  }

  const filtered = visible.length !== transactions.length;

  return (
    <div className="space-y-4">
      {error && (
        <Alert tone="warning" title="Could not remove that transaction">
          {error}
        </Alert>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex gap-1" role="group" aria-label="Filter by type">
          {(["ALL", "BUY", "SELL"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={filters.kind === option}
              onClick={() => setFilters((current) => ({ ...current, kind: option }))}
              className={filters.kind === option ? buttonStyles.secondary : buttonStyles.subtle}
            >
              {option === "ALL" ? "All" : option === "BUY" ? "Buys" : "Sells"}
            </button>
          ))}
        </div>

        <label className="text-xs text-ink-subtle">
          Security
          <select
            className={`${inputStyles} mt-1`}
            value={filters.symbol}
            onChange={(event) => setFilters((current) => ({ ...current, symbol: event.target.value }))}
          >
            <option value="">All</option>
            {symbols.map((symbol) => (
              <option key={symbol} value={symbol}>
                {symbol}
              </option>
            ))}
          </select>
        </label>

        <label className="text-xs text-ink-subtle">
          From
          <input
            type="date"
            className={`${inputStyles} mt-1`}
            value={filters.from}
            onChange={(event) => setFilters((current) => ({ ...current, from: event.target.value }))}
          />
        </label>

        <label className="text-xs text-ink-subtle">
          To
          <input
            type="date"
            className={`${inputStyles} mt-1`}
            value={filters.to}
            onChange={(event) => setFilters((current) => ({ ...current, to: event.target.value }))}
          />
        </label>

        {filtered && (
          <button type="button" className={buttonStyles.subtle} onClick={() => setFilters(EMPTY_FILTERS)}>
            Clear filters
          </button>
        )}
      </div>

      <p className="text-xs text-ink-subtle">
        Showing {visible.length} of {transactions.length} transaction{transactions.length === 1 ? "" : "s"}, newest first.
      </p>

      {visible.length === 0 ? (
        <p className="rounded-md border border-line bg-canvas px-4 py-6 text-center text-sm text-ink-subtle">
          No transaction matches these filters.
        </p>
      ) : (
        <>
          {/* A table on wide screens; the same rows as cards on a phone, where eight columns
              cannot fit without horizontal scrolling. */}
          <div className="hidden overflow-x-auto sm:block">
            <table className="w-full text-sm">
              <caption className="sr-only">Recorded transactions, newest first</caption>
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-subtle">
                  <th scope="col" className="py-2 pr-3 font-medium">Date</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Type</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Security</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Quantity</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Price</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Gross value</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Reference</th>
                  <th scope="col" className="py-2 font-medium"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {visible.map((item) => (
                  <tr key={item.id}>
                    <td className="py-2 pr-3 whitespace-nowrap">{formatTradeDate(item.trade_date)}</td>
                    <td className="py-2 pr-3"><KindBadge kind={item.kind} /></td>
                    <td className="py-2 pr-3 font-medium">
                      {item.symbol}
                      <span className="ml-1 text-xs text-ink-subtle">{item.exchange}</span>
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{item.quantity}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{formatInr(item.price)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {formatInr(grossValue(String(item.quantity), item.price) ?? "0")}
                    </td>
                    <td className="py-2 pr-3 text-xs text-ink-subtle">{item.reference ?? "—"}</td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        className={buttonStyles.subtle}
                        onClick={() => handleDelete(item.id)}
                        disabled={removing === item.id}
                      >
                        {removing === item.id ? "Removing…" : "Remove"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="space-y-2 sm:hidden">
            {visible.map((item) => (
              <li key={item.id} className="rounded-md border border-line bg-canvas px-4 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium">
                    {item.symbol} <span className="text-xs text-ink-subtle">{item.exchange}</span>
                  </span>
                  <KindBadge kind={item.kind} />
                </div>
                <p className="mt-1 text-xs text-ink-subtle">{formatTradeDate(item.trade_date)}</p>
                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                  <div className="flex justify-between gap-2">
                    <dt className="text-ink-subtle">Qty</dt>
                    <dd className="tabular-nums">{item.quantity}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-ink-subtle">Price</dt>
                    <dd className="tabular-nums">{formatInr(item.price)}</dd>
                  </div>
                  <div className="col-span-2 flex justify-between gap-2">
                    <dt className="text-ink-subtle">Gross value</dt>
                    <dd className="tabular-nums">
                      {formatInr(grossValue(String(item.quantity), item.price) ?? "0")}
                    </dd>
                  </div>
                </dl>
                {item.reference && <p className="mt-1 text-xs text-ink-subtle">Ref {item.reference}</p>}
                <button
                  type="button"
                  className={`${buttonStyles.subtle} mt-2`}
                  onClick={() => handleDelete(item.id)}
                  disabled={removing === item.id}
                >
                  {removing === item.id ? "Removing…" : "Remove"}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function KindBadge({ kind }: { kind: "BUY" | "SELL" }) {
  const style =
    kind === "BUY"
      ? "border-positive/40 bg-positive-soft text-positive"
      : "border-caution/40 bg-caution-soft text-caution";
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium ${style}`}>
      {kind === "BUY" ? "Buy" : "Sell"}
    </span>
  );
}
