import Link from "next/link";
import type { ReactNode } from "react";
import {
  AllocationIcon,
  ConcentrationIcon,
  PerformanceIcon,
  RiskIcon,
} from "@/components/icons";

type AnalysisArea = {
  title: string;
  description: string;
  icon: ReactNode;
};

const analysisAreas: AnalysisArea[] = [
  {
    title: "Portfolio allocation",
    description: "How your capital is spread across stocks and sectors.",
    icon: <AllocationIcon className="size-5" />,
  },
  {
    title: "Concentration",
    description:
      "Whether a small number of stocks or sectors dominate your portfolio.",
    icon: <ConcentrationIcon className="size-5" />,
  },
  {
    title: "Risk",
    description:
      "How volatile your portfolio is and how deep its drawdowns have been.",
    icon: <RiskIcon className="size-5" />,
  },
  {
    title: "Performance",
    description:
      "How your portfolio has returned over time compared with a market benchmark.",
    icon: <PerformanceIcon className="size-5" />,
  },
];

const coverage = [
  { label: "Markets", value: "NSE and BSE" },
  { label: "Instruments", value: "Listed equities" },
  { label: "Currency", value: "Indian rupee (INR)" },
];

export default function Home() {
  return (
    <>
      <section className="border-b border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-12 px-5 py-16 sm:px-8 sm:py-24 lg:grid-cols-[1.5fr_1fr] lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">
              Indian equities · NSE &amp; BSE
            </p>
            <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">
              Portfolio Intelligence
            </h1>
            <p className="mt-4 text-xl text-ink sm:text-2xl">
              Understand your portfolio. Measure your risk.
            </p>
            <p className="mt-6 max-w-xl text-base leading-7 text-ink-muted">
              Portfolio Intelligence is a portfolio analytics platform for
              Indian equities. It is being built to help investors see how
              their NSE and BSE holdings are allocated, where risk is
              concentrated and how the portfolio has performed over time.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
              <Link
                href="/analyze"
                className="inline-flex h-11 items-center justify-center rounded-md bg-brand px-5 text-sm font-semibold text-white transition-colors hover:bg-brand-hover"
              >
                Analyze My Portfolio
              </Link>
              <Link
                href="#what-we-analyze"
                className="inline-flex h-11 items-center justify-center rounded-md px-5 text-sm font-medium text-ink-muted transition-colors hover:text-ink"
              >
                What we analyze →
              </Link>
            </div>
            <p className="mt-6 text-sm text-ink-subtle">
              Early build: portfolio analytics are in development and not yet
              available.
            </p>
          </div>

          <div className="rounded-lg border border-line bg-canvas p-6">
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-subtle">
              Coverage
            </h2>
            <dl className="mt-4 divide-y divide-line text-sm">
              {coverage.map((item) => (
                <div key={item.label} className="flex justify-between gap-4 py-3">
                  <dt className="text-ink-muted">{item.label}</dt>
                  <dd className="font-medium">{item.value}</dd>
                </div>
              ))}
              <div className="flex justify-between gap-4 py-3">
                <dt className="text-ink-muted">Status</dt>
                <dd className="flex items-center gap-2 font-medium">
                  <span aria-hidden="true" className="size-2 rounded-full bg-caution" />
                  In development
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </section>

      <section
        id="what-we-analyze"
        className="mx-auto max-w-6xl scroll-mt-8 px-5 py-16 sm:px-8 sm:py-20"
      >
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-subtle">
              What we analyze
            </h2>
            <p className="mt-3 text-2xl font-semibold tracking-tight">
              Four lenses on your portfolio
            </p>
          </div>
          <p className="max-w-sm text-sm leading-6 text-ink-muted">
            These modules are planned and in development. No calculations are
            available yet.
          </p>
        </div>

        <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {analysisAreas.map((area) => (
            <li
              key={area.title}
              className="flex flex-col rounded-lg border border-line bg-surface p-6"
            >
              <div className="flex items-center justify-between">
                <span className="flex size-10 items-center justify-center rounded-md bg-canvas text-brand">
                  {area.icon}
                </span>
                <span className="rounded-full border border-line px-2.5 py-0.5 text-xs font-medium text-ink-subtle">
                  Planned
                </span>
              </div>
              <h3 className="mt-5 text-base font-semibold">{area.title}</h3>
              <p className="mt-2 text-sm leading-6 text-ink-muted">
                {area.description}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
