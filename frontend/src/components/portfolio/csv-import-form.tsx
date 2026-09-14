"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ChangeEvent, useRef, useState } from "react";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { InvestedCapitalCard } from "@/components/portfolio/invested-capital-card";
import { ServiceUnavailable } from "@/components/portfolio/service-unavailable";
import { StepIndicator } from "@/components/portfolio/step-indicator";
import { Alert } from "@/components/ui/alert";
import { DataBadge, DataLegend } from "@/components/ui/data-badge";
import { errorProps, Field } from "@/components/ui/field";
import { buttonStyles, cardStyles, inputStyles } from "@/components/ui/styles";
import {
  ApiError,
  describeError,
  importCsv,
  previewCsv,
  ServiceUnavailableError,
  type CsvPreview,
} from "@/lib/api";
import {
  MAX_CSV_BYTES,
  MAX_HOLDINGS,
  MAX_PORTFOLIO_NAME_LENGTH,
  normalizePortfolioName,
  validatePortfolioName,
} from "@/lib/holding-validation";

const STEPS = [
  { id: "upload", label: "Upload file" },
  { id: "review", label: "Review and save" },
];

const EXAMPLE_CSV = `symbol,exchange,quantity,average_buy_price
HDFCBANK,NSE,20,1650
TCS,NSE,10,3200
RELIANCE,NSE,15,1400`;

export function CsvImportForm() {
  const router = useRouter();
  const latestCheck = useRef(0);

  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string>();
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [fileError, setFileError] = useState<string>();
  const [checking, setChecking] = useState(false);
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();

  const isValid = preview?.is_valid === true;

  function resetFile() {
    latestCheck.current += 1;
    setFile(null);
    setPreview(null);
    setFileError(undefined);
    setSaveError(undefined);
    setChecking(false);
    setFileInputKey((key) => key + 1);
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    const checkId = ++latestCheck.current;
    setFile(selected);
    setPreview(null);
    setFileError(undefined);
    setSaveError(undefined);
    setUnavailable(false);
    if (!selected) return;

    if (!selected.name.toLowerCase().endsWith(".csv")) {
      setFileError("Choose a .csv file.");
      return;
    }
    if (selected.size === 0) {
      setFileError("This file is empty.");
      return;
    }
    if (selected.size > MAX_CSV_BYTES) {
      setFileError("CSV files must be 1 MB or smaller.");
      return;
    }

    setChecking(true);
    try {
      const result = await previewCsv(selected);
      if (checkId === latestCheck.current) setPreview(result);
    } catch (error) {
      if (checkId !== latestCheck.current) return;
      if (error instanceof ServiceUnavailableError) setUnavailable(true);
      else setFileError(describeError(error));
    } finally {
      if (checkId === latestCheck.current) setChecking(false);
    }
  }

  async function handleSave() {
    const problem = validatePortfolioName(name);
    setNameError(problem);
    if (problem || !file) return;

    setSaving(true);
    setSaveError(undefined);
    try {
      const portfolio = await importCsv(normalizePortfolioName(name), file);
      router.push(`/portfolios/${portfolio.id}?created=1`);
    } catch (error) {
      if (error instanceof ServiceUnavailableError) {
        setUnavailable(true);
      } else if (error instanceof ApiError && error.code === "invalid_csv") {
        setPreview({
          is_valid: false,
          holding_count: 0,
          holdings: [],
          total_invested_capital: null,
          errors: error.details.map((detail) => ({
            row: detail.row ?? null,
            column: detail.column ?? null,
            message: detail.message,
          })),
        });
      } else {
        setSaveError(describeError(error));
      }
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <StepIndicator steps={STEPS} current={isValid ? "review" : "upload"} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
        <div className="min-w-0 space-y-6">
          <section className={`${cardStyles} space-y-5 p-5 sm:p-6`}>
            <Field id="portfolio-name" label="Portfolio name" error={nameError}>
              <input
                id="portfolio-name"
                value={name}
                maxLength={MAX_PORTFOLIO_NAME_LENGTH}
                onChange={(event) => {
                  setName(event.target.value);
                  setNameError(undefined);
                }}
                placeholder="e.g. Long-term equity"
                autoComplete="off"
                className={`${inputStyles} sm:max-w-md`}
                {...errorProps("portfolio-name", nameError)}
              />
            </Field>
            <Field
              id="csv-file"
              label="CSV file"
              hint={`A .csv file up to 1 MB with at most ${MAX_HOLDINGS} holdings.`}
            >
              <input
                key={fileInputKey}
                id="csv-file"
                type="file"
                accept=".csv,text/csv"
                onChange={handleFileChange}
                className="block w-full min-w-0 text-sm text-ink-muted file:mr-3 file:h-10 file:cursor-pointer file:rounded-md file:border file:border-line-strong file:bg-surface file:px-4 file:text-sm file:font-medium file:text-ink hover:file:bg-canvas"
              />
            </Field>
            {checking && (
              <p role="status" className="text-sm text-ink-muted">
                Checking {file?.name}…
              </p>
            )}
          </section>

          {unavailable && <ServiceUnavailable action="checked or saved" />}

          {fileError && (
            <Alert tone="error" title="This file can't be used">
              {fileError}
            </Alert>
          )}

          {preview && !preview.is_valid && (
            <CsvErrors preview={preview} fileName={file?.name} onChooseAnother={resetFile} />
          )}

          {preview?.is_valid && (
            <>
              <Alert tone="success" title="File checked">
                {file?.name} is valid: {preview.holding_count}{" "}
                {preview.holding_count === 1 ? "holding is" : "holdings are"} ready to import.
                Review them, then save. Nothing has been saved yet.
              </Alert>
              <DataLegend />
              <section className={cardStyles}>
                <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
                  <h2 className="text-base font-semibold">
                    Holdings{" "}
                    <span className="font-normal text-ink-subtle">({preview.holding_count})</span>
                  </h2>
                  <DataBadge kind="input" />
                </header>
                <HoldingsTable
                  rows={preview.holdings.map((holding) => ({
                    ...holding,
                    key: `${holding.symbol}-${holding.exchange}`,
                  }))}
                  caption="Holdings found in the CSV file"
                />
              </section>
              {preview.total_invested_capital && (
                <InvestedCapitalCard
                  amount={preview.total_invested_capital}
                  holdingCount={preview.holding_count}
                />
              )}
              {saveError && (
                <Alert tone="error" title="The portfolio was not saved">
                  {saveError}
                </Alert>
              )}
            </>
          )}

          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <Link href="/analyze" className={buttonStyles.ghost}>
              Cancel
            </Link>
            {preview?.is_valid && (
              <div className="flex flex-col-reverse gap-3 sm:flex-row">
                <button
                  type="button"
                  onClick={resetFile}
                  className={buttonStyles.secondary}
                  disabled={saving}
                >
                  Choose a different file
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  className={buttonStyles.primary}
                  disabled={saving}
                >
                  {saving ? "Saving…" : "Save Portfolio"}
                </button>
              </div>
            )}
          </div>
        </div>

        <CsvFormatGuide />
      </div>
    </div>
  );
}

function CsvErrors({
  preview,
  fileName,
  onChooseAnother,
}: {
  preview: CsvPreview;
  fileName?: string;
  onChooseAnother: () => void;
}) {
  const count = preview.errors.length;
  return (
    <section className={cardStyles}>
      <div className="p-5 sm:p-6">
        <Alert tone="error" title={`${count} ${count === 1 ? "problem" : "problems"} found in ${fileName ?? "the file"}`}>
          Nothing has been saved. Fix the file and upload it again.
        </Alert>
      </div>
      <div className="relative overflow-x-auto border-t border-line">
        <table className="w-full min-w-[28rem] text-sm">
          <caption className="sr-only">Problems found in the CSV file</caption>
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-ink-subtle">
              <th scope="col" className="px-5 py-3 font-medium">
                Row
              </th>
              <th scope="col" className="px-3 py-3 font-medium">
                Column
              </th>
              <th scope="col" className="px-5 py-3 font-medium">
                Problem
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {preview.errors.map((issue, index) => (
              <tr key={`${issue.row}-${issue.column}-${index}`} className="align-top">
                <td className="px-5 py-3 font-mono tabular-nums">{issue.row ?? "—"}</td>
                <td className="px-3 py-3 font-mono text-ink-muted">{issue.column ?? "—"}</td>
                <td className="px-5 py-3">{issue.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-line px-5 py-4 sm:px-6">
        <button type="button" onClick={onChooseAnother} className={buttonStyles.secondary}>
          Choose a different file
        </button>
      </div>
    </section>
  );
}

function CsvFormatGuide() {
  return (
    <aside className={`${cardStyles} min-w-0 p-5 text-sm sm:p-6`} aria-labelledby="csv-format-heading">
      <h2 id="csv-format-heading" className="text-base font-semibold">
        CSV format
      </h2>
      <p className="mt-2 leading-6 text-ink-muted">
        The first line must be this header. Each following line is one holding.
      </p>
      <pre className="mt-3 whitespace-pre-wrap rounded-md bg-canvas p-3 font-mono text-xs leading-5 [overflow-wrap:anywhere]">
        {EXAMPLE_CSV}
      </pre>
      <dl className="mt-4 space-y-3">
        <div>
          <dt className="font-mono text-xs font-semibold">symbol</dt>
          <dd className="text-ink-muted">NSE or BSE symbol, e.g. HDFCBANK or M&amp;M</dd>
        </div>
        <div>
          <dt className="font-mono text-xs font-semibold">exchange</dt>
          <dd className="text-ink-muted">NSE or BSE</dd>
        </div>
        <div>
          <dt className="font-mono text-xs font-semibold">quantity</dt>
          <dd className="text-ink-muted">Whole number of shares, greater than 0</dd>
        </div>
        <div>
          <dt className="font-mono text-xs font-semibold">average_buy_price</dt>
          <dd className="text-ink-muted">Price per share in ₹, greater than 0, up to 4 decimals</dd>
        </div>
      </dl>
      <ul className="mt-4 list-disc space-y-1.5 pl-5 leading-6 text-ink-muted">
        <li>No commas or ₹ symbols inside numbers.</li>
        <li>No extra columns.</li>
        <li>List each symbol and exchange once. Duplicates are rejected, not merged.</li>
        <li>If any row has a problem, nothing is saved.</li>
      </ul>
      <a
        href="/sample-portfolio.csv"
        download
        className={`${buttonStyles.secondary} mt-5 w-full`}
      >
        Download sample CSV
      </a>
    </aside>
  );
}
