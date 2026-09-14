import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { ManualEntryIcon, UploadIcon } from "@/components/icons";
import { PageHeader } from "@/components/portfolio/page-header";
import { SavedPortfolios } from "@/components/portfolio/saved-portfolios";
import { eyebrowStyles } from "@/components/ui/styles";

export const metadata: Metadata = {
  title: "Analyze My Portfolio",
};

type CreateOption = {
  href: string;
  title: string;
  description: string;
  action: string;
  icon: ReactNode;
};

const createOptions: CreateOption[] = [
  {
    href: "/portfolios/new",
    title: "Enter holdings manually",
    description:
      "Add each stock with its exchange, quantity and average buy price, then review and save.",
    action: "Create portfolio",
    icon: <ManualEntryIcon className="size-5" />,
  },
  {
    href: "/portfolios/import",
    title: "Upload a CSV file",
    description:
      "Import holdings from a CSV file with symbol, exchange, quantity and average_buy_price columns.",
    action: "Import CSV",
    icon: <UploadIcon className="size-5" />,
  },
];

export default function AnalyzePage() {
  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-14">
      <PageHeader
        breadcrumbs={[{ label: "Portfolios" }]}
        title="Analyze my portfolio"
        description="Start by creating a portfolio from your NSE and BSE holdings. Analytics such as allocation, concentration, risk and performance are planned for later releases."
      />

      <section aria-labelledby="create-heading" className="mt-10">
        <h2 id="create-heading" className={eyebrowStyles}>
          Create a portfolio
        </h2>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          {createOptions.map((option) => (
            <Link
              key={option.href}
              href={option.href}
              className="flex flex-col rounded-lg border border-line bg-surface p-6 transition-colors hover:border-line-strong hover:bg-canvas/40"
            >
              <span className="flex size-10 items-center justify-center rounded-md bg-canvas text-brand">
                {option.icon}
              </span>
              <h3 className="mt-5 text-base font-semibold">{option.title}</h3>
              <p className="mt-2 flex-1 text-sm leading-6 text-ink-muted">{option.description}</p>
              <span className="mt-5 text-sm font-semibold text-brand">{option.action} →</span>
            </Link>
          ))}
        </div>
      </section>

      <section aria-labelledby="saved-heading" className="mt-12">
        <h2 id="saved-heading" className={eyebrowStyles}>
          Saved portfolios
        </h2>
        <div className="mt-4">
          <SavedPortfolios />
        </div>
      </section>
    </div>
  );
}
