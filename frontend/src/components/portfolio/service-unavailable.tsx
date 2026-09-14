import { Alert } from "@/components/ui/alert";

const SETUP_URL = "https://github.com/pgp41370-coder/portfolio-intelligence#5-local-setup";

export function ServiceUnavailable({ action = "saved or loaded" }: { action?: string }) {
  return (
    <Alert tone="warning" title="Portfolio storage isn't available in this deployment">
      <p>
        This site isn&apos;t connected to the portfolio API and database yet, so portfolios
        can&apos;t be {action} here. The complete flow works when the app runs locally with its
        FastAPI backend and PostgreSQL database.
      </p>
      <p className="mt-2">
        <a href={SETUP_URL} className="font-medium underline underline-offset-2">
          Local setup instructions
        </a>
      </p>
    </Alert>
  );
}
