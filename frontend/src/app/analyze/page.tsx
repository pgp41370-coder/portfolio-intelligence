import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Analyze My Portfolio",
};

const plannedInputs = [
  "Stock symbol (NSE or BSE)",
  "Quantity held",
  "Average purchase price (₹)",
];

export default function AnalyzePage() {
  return (
    <section className="mx-auto w-full max-w-3xl px-5 py-16 sm:px-8 sm:py-24">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">
        Portfolio analysis
      </p>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">
        Analyze my portfolio
      </h1>
      <p className="mt-4 text-base leading-7 text-ink-muted">
        Portfolio input is not available yet. This page is a placeholder for
        the analysis workflow, which is the next part of the product being
        built.
      </p>

      <div className="mt-10 rounded-lg border border-line bg-surface p-6">
        <div className="flex items-start justify-between gap-4">
          <h2 className="text-base font-semibold">Coming next: enter your holdings</h2>
          <span className="shrink-0 rounded-full border border-line px-2.5 py-0.5 text-xs font-medium text-ink-subtle">
            Planned
          </span>
        </div>
        <p className="mt-2 text-sm leading-6 text-ink-muted">
          You will be able to add each position in your portfolio with:
        </p>
        <ul className="mt-4 divide-y divide-line border-y border-line text-sm">
          {plannedInputs.map((input) => (
            <li key={input} className="py-3">
              {input}
            </li>
          ))}
        </ul>
      </div>

      <Link
        href="/"
        className="mt-10 inline-flex text-sm font-medium text-ink-muted transition-colors hover:text-ink"
      >
        ← Back to home
      </Link>
    </section>
  );
}
