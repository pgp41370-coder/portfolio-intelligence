"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";
import { HoldingsTable } from "@/components/portfolio/holdings-table";
import { InvestedCapitalCard } from "@/components/portfolio/invested-capital-card";
import { ServiceUnavailable } from "@/components/portfolio/service-unavailable";
import { StepIndicator } from "@/components/portfolio/step-indicator";
import { Alert } from "@/components/ui/alert";
import { DataBadge, DataLegend } from "@/components/ui/data-badge";
import { errorProps, Field, FieldError } from "@/components/ui/field";
import { buttonStyles, cardStyles, inputStyles } from "@/components/ui/styles";
import {
  createPortfolio,
  describeError,
  EXCHANGES,
  ServiceUnavailableError,
  type HoldingInput,
} from "@/lib/api";
import { investedCapital } from "@/lib/decimal";
import { formatInr } from "@/lib/format";
import {
  MAX_HOLDINGS,
  MAX_PORTFOLIO_NAME_LENGTH,
  MAX_SYMBOL_LENGTH,
  normalizePortfolioName,
  validateHolding,
  validatePortfolioName,
  type HoldingFormErrors,
  type HoldingFormValues,
} from "@/lib/holding-validation";

type DraftHolding = HoldingInput & { key: string };
type Step = "edit" | "review";
type SaveError = { unavailable: boolean; message: string };

const STEPS = [
  { id: "edit", label: "Name and holdings" },
  { id: "review", label: "Review and save" },
];

const EMPTY_FORM: HoldingFormValues = {
  symbol: "",
  exchange: "NSE",
  quantity: "",
  averageBuyPrice: "",
};

export function ManualPortfolioForm() {
  const router = useRouter();
  const nextKey = useRef(0);
  const symbolInput = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<Step>("edit");
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string>();
  const [form, setForm] = useState<HoldingFormValues>(EMPTY_FORM);
  const [formErrors, setFormErrors] = useState<HoldingFormErrors>({});
  const [holdings, setHoldings] = useState<DraftHolding[]>([]);
  const [listError, setListError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<SaveError>();

  const total = investedCapital(holdings);

  function updateField(field: keyof HoldingFormValues, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setFormErrors((current) => ({ ...current, [field]: undefined }));
  }

  function handleAddHolding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (holdings.length >= MAX_HOLDINGS) {
      setFormErrors({ symbol: `A portfolio can have at most ${MAX_HOLDINGS} holdings.` });
      return;
    }
    const { errors, holding } = validateHolding(form, holdings);
    setFormErrors(errors);
    if (!holding) return;

    nextKey.current += 1;
    setHoldings((current) => [...current, { ...holding, key: `holding-${nextKey.current}` }]);
    setListError(undefined);
    setForm((current) => ({ ...EMPTY_FORM, exchange: current.exchange }));
    symbolInput.current?.focus();
  }

  function handleRemove(key: string) {
    setHoldings((current) => current.filter((holding) => holding.key !== key));
  }

  function handleReview() {
    const nameProblem = validatePortfolioName(name);
    const listProblem = holdings.length === 0 ? "Add at least one holding before reviewing." : undefined;
    setNameError(nameProblem);
    setListError(listProblem);
    if (nameProblem || listProblem) return;

    setSaveError(undefined);
    setStep("review");
    window.scrollTo({ top: 0 });
  }

  async function handleSave() {
    setSaving(true);
    setSaveError(undefined);
    try {
      const portfolio = await createPortfolio({
        name: normalizePortfolioName(name),
        holdings: holdings.map(({ symbol, exchange, quantity, average_buy_price }) => ({
          symbol,
          exchange,
          quantity,
          average_buy_price,
        })),
      });
      router.push(`/portfolios/${portfolio.id}?created=1`);
    } catch (error) {
      setSaveError({
        unavailable: error instanceof ServiceUnavailableError,
        message: describeError(error),
      });
      setSaving(false);
    }
  }

  if (step === "review") {
    return (
      <div className="space-y-6">
        <StepIndicator steps={STEPS} current="review" />
        <DataLegend />

        <section className={`${cardStyles} p-5 sm:p-6`}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold">Portfolio name</h2>
            <DataBadge kind="input" />
          </div>
          <p className="mt-2 text-sm [overflow-wrap:anywhere]">{normalizePortfolioName(name)}</p>
        </section>

        <section className={cardStyles}>
          <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
            <h2 className="text-base font-semibold">
              Holdings <span className="font-normal text-ink-subtle">({holdings.length})</span>
            </h2>
            <DataBadge kind="input" />
          </header>
          <HoldingsTable rows={holdings} caption="Holdings to be saved" />
        </section>

        <InvestedCapitalCard amount={total} holdingCount={holdings.length} />

        {saveError &&
          (saveError.unavailable ? (
            <ServiceUnavailable action="saved" />
          ) : (
            <Alert tone="error" title="The portfolio was not saved">
              {saveError.message}
            </Alert>
          ))}

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Link href="/analyze" className={buttonStyles.ghost}>
            Cancel
          </Link>
          <div className="flex flex-col-reverse gap-3 sm:flex-row">
            <button
              type="button"
              className={buttonStyles.secondary}
              onClick={() => setStep("edit")}
              disabled={saving}
            >
              Back to edit
            </button>
            <button type="button" className={buttonStyles.primary} onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : "Save Portfolio"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <StepIndicator steps={STEPS} current="edit" />

      <section className={`${cardStyles} p-5 sm:p-6`}>
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
      </section>

      <section className={cardStyles}>
        <header className="border-b border-line px-5 py-4 sm:px-6">
          <h2 className="text-base font-semibold">Add a holding</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Enter one position at a time. Symbols are checked for format only, not against NSE or
            BSE listings.
          </p>
        </header>
        <form
          onSubmit={handleAddHolding}
          noValidate
          className="grid grid-cols-1 gap-4 px-5 py-5 sm:grid-cols-2 sm:px-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto] lg:items-start"
        >
          <Field id="holding-symbol" label="Stock Symbol" error={formErrors.symbol}>
            <input
              ref={symbolInput}
              id="holding-symbol"
              value={form.symbol}
              onChange={(event) => updateField("symbol", event.target.value.toUpperCase())}
              placeholder="HDFCBANK"
              maxLength={MAX_SYMBOL_LENGTH}
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              className={inputStyles}
              {...errorProps("holding-symbol", formErrors.symbol)}
            />
          </Field>
          <Field id="holding-exchange" label="Exchange" error={formErrors.exchange}>
            <select
              id="holding-exchange"
              value={form.exchange}
              onChange={(event) => updateField("exchange", event.target.value)}
              className={inputStyles}
              {...errorProps("holding-exchange", formErrors.exchange)}
            >
              {EXCHANGES.map((exchange) => (
                <option key={exchange} value={exchange}>
                  {exchange}
                </option>
              ))}
            </select>
          </Field>
          <Field id="holding-quantity" label="Quantity" error={formErrors.quantity}>
            <input
              id="holding-quantity"
              value={form.quantity}
              onChange={(event) => updateField("quantity", event.target.value)}
              placeholder="20"
              inputMode="numeric"
              autoComplete="off"
              className={inputStyles}
              {...errorProps("holding-quantity", formErrors.quantity)}
            />
          </Field>
          <Field id="holding-price" label="Average Buy Price (₹)" error={formErrors.averageBuyPrice}>
            <input
              id="holding-price"
              value={form.averageBuyPrice}
              onChange={(event) => updateField("averageBuyPrice", event.target.value)}
              placeholder="1650.00"
              inputMode="decimal"
              autoComplete="off"
              className={inputStyles}
              {...errorProps("holding-price", formErrors.averageBuyPrice)}
            />
          </Field>
          <div className="sm:col-span-2 lg:col-span-1 lg:pt-7">
            <button type="submit" className={`${buttonStyles.secondary} w-full lg:w-auto`}>
              Add Holding
            </button>
          </div>
        </form>
      </section>

      <section className={cardStyles}>
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4 sm:px-6">
          <h2 className="text-base font-semibold">
            Holdings <span className="font-normal text-ink-subtle">({holdings.length})</span>
          </h2>
          <DataBadge kind="input" />
        </header>
        <HoldingsTable
          rows={holdings}
          caption="Holdings added so far"
          emptyMessage="No holdings added yet. Use the form above to add your first holding."
          renderAction={(row) => (
            <button
              type="button"
              onClick={() => handleRemove(row.key)}
              className={buttonStyles.danger}
              aria-label={`Remove ${row.symbol} on ${row.exchange}`}
            >
              <span className="sm:hidden">Remove</span>
              <span className="hidden sm:inline">Remove Holding</span>
            </button>
          )}
        />
        {holdings.length > 0 && (
          <div className="flex items-center justify-between gap-4 border-t border-line px-5 py-4 text-sm sm:px-6">
            <span className="flex flex-wrap items-center gap-2 text-ink-muted">
              Total Invested Capital <DataBadge kind="calculated" />
            </span>
            <span className="font-mono font-semibold tabular-nums">{formatInr(total)}</span>
          </div>
        )}
        {listError && (
          <div className="px-5 pb-4 sm:px-6">
            <FieldError id="holdings-error">{listError}</FieldError>
          </div>
        )}
      </section>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Link href="/analyze" className={buttonStyles.ghost}>
          Cancel
        </Link>
        <button type="button" onClick={handleReview} className={buttonStyles.primary}>
          Review Portfolio
        </button>
      </div>
    </div>
  );
}
