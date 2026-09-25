"use client";

import { type FormEvent, useMemo, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { errorProps, Field } from "@/components/ui/field";
import { buttonStyles, inputStyles } from "@/components/ui/styles";
import {
  addTransactions,
  describeError,
  EXCHANGES,
  ServiceUnavailableError,
  type Transaction,
  type TransactionInput,
} from "@/lib/api";
import { formatInr } from "@/lib/format";
import {
  EMPTY_TRANSACTION_FORM,
  grossValue,
  netCashFlow,
  positionsFrom,
  securityKey,
  validateTransaction,
  type TransactionFormErrors,
  type TransactionFormValues,
} from "@/lib/transaction-validation";

type Step = "edit" | "review";

type TransactionEntryFormProps = {
  portfolioId: string;
  /** The stored ledger, used to check a sale against the position actually held. */
  transactions: Transaction[];
  /** The latest completed NSE session, so a future-dated trade is caught before submitting. */
  latestSession?: string;
  onSaved: (created: Transaction[]) => void;
};

export function TransactionEntryForm({
  portfolioId,
  transactions,
  latestSession,
  onSaved,
}: TransactionEntryFormProps) {
  const [step, setStep] = useState<Step>("edit");
  const [values, setValues] = useState<TransactionFormValues>(EMPTY_TRANSACTION_FORM);
  const [errors, setErrors] = useState<TransactionFormErrors>({});
  const [pending, setPending] = useState<TransactionInput>();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();

  const positions = useMemo(() => positionsFrom(transactions), [transactions]);
  const heldSymbols = useMemo(
    () => [...new Set(transactions.map((item) => item.symbol))].sort(),
    [transactions],
  );
  const gross = grossValue(values.quantity, values.price);
  const flow = netCashFlow(values.kind, values.quantity, values.price, values.fees);
  const held = values.symbol
    ? positions.get(securityKey(values.symbol.trim().toUpperCase(), values.exchange || "NSE")) ?? 0
    : 0;

  function update(field: keyof TransactionFormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
    setSaveError(undefined);
  }

  function handleReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = validateTransaction(values, { latestSession, positions });
    setErrors(result.errors);
    if (!result.transaction) return;
    setPending(result.transaction);
    setStep("review");
  }

  async function handleSubmit() {
    // Guard against a double click sending the same trade twice: the API would accept both,
    // because two identical trades on one day are legitimate.
    if (!pending || saving) return;
    setSaving(true);
    setSaveError(undefined);
    try {
      const created = await addTransactions(portfolioId, [pending]);
      onSaved(created);
      setValues({ ...EMPTY_TRANSACTION_FORM, tradeDate: pending.trade_date });
      setPending(undefined);
      setStep("edit");
    } catch (error: unknown) {
      setSaveError(
        error instanceof ServiceUnavailableError
          ? "The portfolio service is not reachable right now. Nothing was saved."
          : describeError(error),
      );
      setStep("edit");
    } finally {
      setSaving(false);
    }
  }

  if (step === "review" && pending) {
    return (
      <div className="space-y-4">
        <h3 className="text-sm font-semibold">Check this transaction before saving</h3>
        <dl className="divide-y divide-line rounded-md border border-line bg-canvas text-sm">
          <Row label="Type" value={pending.kind === "BUY" ? "Buy" : "Sell"} />
          <Row label="Security" value={`${pending.symbol} · ${pending.exchange}`} />
          <Row label="Trade date" value={pending.trade_date} />
          <Row label="Quantity" value={String(pending.quantity)} />
          <Row label="Price" value={formatInr(pending.price)} />
          <Row label="Gross value" value={gross ? formatInr(gross) : "—"} />
          <Row label="Fees" value={formatInr(pending.fees ?? "0")} />
          <Row
            label={pending.kind === "BUY" ? "Cash out" : "Cash in"}
            value={flow ? formatInr(flow.startsWith("-") ? flow.slice(1) : flow) : "—"}
          />
          {pending.reference && <Row label="Reference" value={pending.reference} />}
        </dl>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonStyles.primary} onClick={handleSubmit} disabled={saving}>
            {saving ? "Saving…" : "Save transaction"}
          </button>
          <button
            type="button"
            className={buttonStyles.subtle}
            onClick={() => setStep("edit")}
            disabled={saving}
          >
            Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleReview} className="space-y-4" noValidate>
      {saveError && (
        <Alert tone="warning" title="Transaction not saved">
          {saveError}
        </Alert>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id="tx-kind" label="Type">
          <div className="flex gap-2" role="group" aria-label="Transaction type">
            {(["BUY", "SELL"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={values.kind === option}
                onClick={() => update("kind", option)}
                className={values.kind === option ? buttonStyles.secondary : buttonStyles.subtle}
              >
                {option === "BUY" ? "Buy" : "Sell"}
              </button>
            ))}
          </div>
        </Field>

        <Field
          id="tx-symbol"
          label="Security"
          error={errors.symbol}
          hint={values.kind === "SELL" && values.symbol ? `${held} held` : "For example HDFCBANK"}
        >
          <input
            id="tx-symbol"
            list="tx-held-symbols"
            className={inputStyles}
            value={values.symbol}
            onChange={(event) => update("symbol", event.target.value)}
            autoComplete="off"
            spellCheck={false}
            maxLength={20}
            {...errorProps("tx-symbol", errors.symbol)}
          />
          {/* Securities already in the ledger are offered, but any symbol may be typed. */}
          <datalist id="tx-held-symbols">
            {heldSymbols.map((symbol) => (
              <option key={symbol} value={symbol} />
            ))}
          </datalist>
        </Field>

        <Field id="tx-exchange" label="Exchange" error={errors.exchange}>
          <select
            id="tx-exchange"
            className={inputStyles}
            value={values.exchange}
            onChange={(event) => update("exchange", event.target.value)}
            {...errorProps("tx-exchange", errors.exchange)}
          >
            {EXCHANGES.map((exchange) => (
              <option key={exchange} value={exchange}>
                {exchange}
              </option>
            ))}
          </select>
        </Field>

        <Field id="tx-date" label="Trade date" error={errors.tradeDate} hint={latestSession ? `On or before ${latestSession}` : undefined}>
          <input
            id="tx-date"
            type="date"
            className={inputStyles}
            value={values.tradeDate}
            max={latestSession}
            onChange={(event) => update("tradeDate", event.target.value)}
            {...errorProps("tx-date", errors.tradeDate)}
          />
        </Field>

        <Field id="tx-quantity" label="Quantity" error={errors.quantity}>
          <input
            id="tx-quantity"
            inputMode="numeric"
            className={inputStyles}
            value={values.quantity}
            onChange={(event) => update("quantity", event.target.value)}
            {...errorProps("tx-quantity", errors.quantity)}
          />
        </Field>

        <Field id="tx-price" label="Price per share" error={errors.price}>
          <input
            id="tx-price"
            inputMode="decimal"
            className={inputStyles}
            value={values.price}
            onChange={(event) => update("price", event.target.value)}
            {...errorProps("tx-price", errors.price)}
          />
        </Field>

        <Field id="tx-fees" label="Fees (optional)" error={errors.fees} hint="Brokerage, taxes and charges in total">
          <input
            id="tx-fees"
            inputMode="decimal"
            className={inputStyles}
            value={values.fees}
            onChange={(event) => update("fees", event.target.value)}
            {...errorProps("tx-fees", errors.fees)}
          />
        </Field>

        <Field id="tx-reference" label="Reference (optional)" error={errors.reference} hint="For example a broker order id">
          <input
            id="tx-reference"
            className={inputStyles}
            value={values.reference}
            onChange={(event) => update("reference", event.target.value)}
            maxLength={64}
            {...errorProps("tx-reference", errors.reference)}
          />
        </Field>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-canvas px-4 py-3">
        <div className="text-sm">
          <span className="text-ink-subtle">Gross value</span>{" "}
          <span className="font-semibold tabular-nums">{gross ? formatInr(gross) : "—"}</span>
          {flow && (
            <span className="ml-3 text-ink-subtle">
              {values.kind === "BUY" ? "cash out" : "cash in"}{" "}
              <span className="tabular-nums">
                {formatInr(flow.startsWith("-") ? flow.slice(1) : flow)}
              </span>
            </span>
          )}
        </div>
        <button type="submit" className={buttonStyles.primary}>
          Review
        </button>
      </div>
    </form>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-4 py-2.5">
      <dt className="text-ink-subtle">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}
