import type { Metadata } from "next";
import { ManualPortfolioForm } from "@/components/portfolio/manual-portfolio-form";
import { PageHeader } from "@/components/portfolio/page-header";

export const metadata: Metadata = {
  title: "Create Portfolio",
};

export default function NewPortfolioPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-10 sm:px-8 sm:py-14">
      <PageHeader
        breadcrumbs={[{ label: "Portfolios", href: "/analyze" }, { label: "New portfolio" }]}
        title="Create a portfolio"
        description="Enter your holdings manually. Nothing is saved until you review the portfolio and choose Save Portfolio."
      />
      <div className="mt-8">
        <ManualPortfolioForm />
      </div>
    </div>
  );
}
