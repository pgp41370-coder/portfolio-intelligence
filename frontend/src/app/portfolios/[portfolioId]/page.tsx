import type { Metadata } from "next";
import { PortfolioView } from "@/components/portfolio/portfolio-view";

export const metadata: Metadata = {
  title: "Portfolio",
};

export default async function PortfolioPage(props: PageProps<"/portfolios/[portfolioId]">) {
  const { portfolioId } = await props.params;
  const { created } = await props.searchParams;

  return (
    <div className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8 sm:py-14">
      <PortfolioView portfolioId={portfolioId} justCreated={created === "1"} />
    </div>
  );
}
