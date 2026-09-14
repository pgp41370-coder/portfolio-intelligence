import type { Metadata } from "next";
import { CsvImportForm } from "@/components/portfolio/csv-import-form";
import { PageHeader } from "@/components/portfolio/page-header";

export const metadata: Metadata = {
  title: "Import Portfolio from CSV",
};

export default function ImportPortfolioPage() {
  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-14">
      <PageHeader
        breadcrumbs={[{ label: "Portfolios", href: "/analyze" }, { label: "Import CSV" }]}
        title="Import a portfolio from CSV"
        description="Upload a CSV file of your holdings. Every row is checked first, and nothing is saved until you confirm."
      />
      <div className="mt-8">
        <CsvImportForm />
      </div>
    </div>
  );
}
