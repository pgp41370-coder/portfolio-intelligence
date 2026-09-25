"use client";

import { type ChangeEvent, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { buttonStyles, inputStyles } from "@/components/ui/styles";
import {
  ApiError,
  describeError,
  importTransactionCsv,
  previewTransactionCsv,
  ServiceUnavailableError,
  type Transaction,
  type TransactionCsvPreview,
} from "@/lib/api";
import { formatInr } from "@/lib/format";
import { MAX_CSV_BYTES } from "@/lib/holding-validation";

const EXAMPLE_CSV = `trade_date,symbol,exchange,type,quantity,price,fees,reference
2026-09-14,HDFCBANK,NSE,BUY,20,1650,25,ORD-1
2026-09-15,TCS,NSE,BUY,10,3200,30,ORD-2
2026-09-16,HDFCBANK,NSE,SELL,5,1700,20,ORD-3`;

type TransactionCsvImportProps = {
  portfolioId: string;
  onImported: (created: Transaction[]) => void;
};

export function TransactionCsvImport({ portfolioId, onImported }: TransactionCsvImportProps) {
  const latestCheck = useRef(0);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [fileError, setFileError] = useState<string>();
  const [checking, setChecking] = useState(false);
  const [preview, setPreview] = useState<TransactionCsvPreview | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string>();
  const [imported, setImported] = useState<number>();

  function reset() {
    setFile(null);
    setPreview(null);
    setFileError(undefined);
    setImportError(undefined);
    setFileInputKey((key) => key + 1);
  }

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null;
    setPreview(null);
    setImportError(undefined);
    setImported(undefined);
    setFile(chosen);
    if (!chosen) return;
    if (chosen.size > MAX_CSV_BYTES) {
      setFileError("CSV files must be 1 MB or smaller.");
      return;
    }
    setFileError(undefined);

    // Only the newest check may update the view, so a quick second choice cannot be
    // overwritten by a slower earlier response.
    const check = ++latestCheck.current;
    setChecking(true);
    try {
      const result = await previewTransactionCsv(portfolioId, chosen);
      if (check === latestCheck.current) setPreview(result);
    } catch (error: unknown) {
      if (check !== latestCheck.current) return;
      setFileError(
        error instanceof ServiceUnavailableError
          ? "The portfolio service is not reachable right now."
          : describeError(error),
      );
    } finally {
      if (check === latestCheck.current) setChecking(false);
    }
  }

  async function handleImport() {
    if (!file || importing || !preview?.is_valid) return;
    setImporting(true);
    setImportError(undefined);
    try {
      const created = await importTransactionCsv(portfolioId, file);
      setImported(created.length);
      onImported(created);
      reset();
    } catch (error: unknown) {
      if (error instanceof ApiError && error.code === "invalid_csv") {
        // The file changed, or the ledger did, between preview and import.
        setPreview({
          is_valid: false,
          transaction_count: 0,
          transactions: [],
          net_cash_flow: null,
          errors: error.details.map((detail) => ({
            row: (detail as { row?: number | null }).row ?? null,
            column: (detail as { column?: string | null }).column ?? null,
            message: detail.message,
          })),
        });
        setImportError("Nothing was imported. The file no longer validates against this ledger.");
      } else {
        setImportError(
          error instanceof ServiceUnavailableError
            ? "The portfolio service is not reachable right now. Nothing was imported."
            : describeError(error),
        );
      }
    } finally {
      setImporting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="tx-csv" className="text-sm font-medium text-ink">
          Transactions CSV
        </label>
        <input
          key={fileInputKey}
          id="tx-csv"
          type="file"
          accept=".csv,text/csv"
          className={`${inputStyles} mt-2`}
          onChange={handleFile}
        />
        <p className="mt-1.5 text-xs text-ink-subtle">
          Required columns: trade_date, symbol, exchange, type, quantity, price. Optional: fees,
          reference. Sort oldest first. Up to 1 MB.
        </p>
      </div>

      {fileError && (
        <Alert tone="warning" title="That file cannot be read">
          {fileError}
        </Alert>
      )}

      {checking && <p className="text-sm text-ink-subtle">Checking the file…</p>}

      {imported !== undefined && (
        <Alert tone="success" title="Transactions imported">
          {imported} transaction{imported === 1 ? "" : "s"} added to this portfolio.
        </Alert>
      )}

      {preview && !preview.is_valid && (
        <Alert tone="warning" title="This file cannot be imported">
          <p>
            Nothing will be saved until every problem is fixed — a partly imported ledger would
            produce a wrong cost basis and a wrong return without saying so.
          </p>
          <ul className="mt-2 space-y-1">
            {preview.errors.map((issue, index) => (
              <li key={`${issue.row ?? "file"}-${index}`}>
                {issue.row ? <span className="font-medium">Row {issue.row}</span> : <span className="font-medium">File</span>}
                {issue.column ? ` · ${issue.column}` : ""}: {issue.message}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      {preview?.is_valid && (
        <div className="space-y-3">
          <div className="rounded-md border border-line bg-canvas px-4 py-3 text-sm">
            <p>
              <span className="font-semibold">{preview.transaction_count}</span> transaction
              {preview.transaction_count === 1 ? "" : "s"} ready to import.
              {preview.net_cash_flow && (
                <>
                  {" "}Net cash movement{" "}
                  <span className="tabular-nums">
                    {preview.net_cash_flow.startsWith("-")
                      ? `${formatInr(preview.net_cash_flow.slice(1))} in`
                      : `${formatInr(preview.net_cash_flow)} out`}
                  </span>
                  .
                </>
              )}
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Transactions that would be imported</caption>
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-subtle">
                  <th scope="col" className="py-2 pr-3 font-medium">Date</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Type</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Security</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Quantity</th>
                  <th scope="col" className="py-2 text-right font-medium">Price</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {preview.transactions.slice(0, 25).map((item, index) => (
                  <tr key={`${item.trade_date}-${item.symbol}-${index}`}>
                    <td className="py-2 pr-3 whitespace-nowrap">{item.trade_date}</td>
                    <td className="py-2 pr-3">{item.kind}</td>
                    <td className="py-2 pr-3 font-medium">{item.symbol}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{item.quantity}</td>
                    <td className="py-2 text-right tabular-nums">{formatInr(item.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {preview.transactions.length > 25 && (
              <p className="mt-2 text-xs text-ink-subtle">
                Showing the first 25 of {preview.transactions.length}. All of them will be imported.
              </p>
            )}
          </div>

          {importError && (
            <Alert tone="warning" title="Import failed">
              {importError}
            </Alert>
          )}

          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonStyles.primary} onClick={handleImport} disabled={importing}>
              {importing ? "Importing…" : `Import ${preview.transaction_count} transaction${preview.transaction_count === 1 ? "" : "s"}`}
            </button>
            <button type="button" className={buttonStyles.subtle} onClick={reset} disabled={importing}>
              Choose a different file
            </button>
          </div>
        </div>
      )}

      <details className="text-sm">
        <summary className="cursor-pointer text-ink-subtle">Example file</summary>
        <pre className="mt-2 overflow-x-auto rounded-md border border-line bg-canvas p-3 text-xs">
          {EXAMPLE_CSV}
        </pre>
      </details>
    </div>
  );
}
