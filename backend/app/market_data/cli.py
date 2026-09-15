"""Command-line entry point for market-data synchronisation.

Run from the backend directory:

    uv run python -m app.market_data.cli sync-listings
    uv run python -m app.market_data.cli sync-prices --dry-run
    uv run python -m app.market_data.cli sync-prices [--portfolio-id UUID] [--force]
    uv run python -m app.market_data.cli status

Exit codes: 0 success, 1 failed or partial (including database errors), 2 configuration
error, 3 stopped by rate limit or request budget, 4 another sync is running.

Output may appear in public CI logs, so database errors are reported by type only: driver
messages can contain host and user names.
"""

import argparse
import json
import logging
import sys
import uuid

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.database import get_engine, get_session_factory
from app.market_data.calendar import now_utc
from app.market_data.exceptions import SyncAlreadyRunningError
from app.market_data.ingestion.sync import sync_daily_prices, sync_security_master
from app.market_data.providers import build_provider
from app.market_data.service import get_status

EXIT_CODES = {"succeeded": 0, "dry_run": 0, "partial": 1, "failed": 1, "rate_limited": 3, "budget_exhausted": 3}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.market_data.cli",
        description="Portfolio Intelligence market-data sync (NSE end-of-day prices).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync-listings", help="Load the provider's security list (not metered).")
    prices = commands.add_parser("sync-prices", help="Fetch NSE end-of-day prices for held securities.")
    prices.add_argument("--portfolio-id", type=uuid.UUID, help="Only securities held in this portfolio.")
    prices.add_argument("--dry-run", action="store_true", help="Show what would be requested without calling the provider.")
    prices.add_argument("--force", action="store_true", help="Request even securities that look up to date.")
    commands.add_parser("status", help="Show market-data status.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_settings()
    if args.command != "status" and settings.database_pool_mode == "transaction":
        print(
            "Market-data syncs hold a session-level database lock and need a session-mode connection "
            "(Supabase session pooler or a direct connection), not DATABASE_POOL_MODE=transaction.",
            file=sys.stderr,
        )
        return 2
    try:
        return _run(args, settings)
    except SQLAlchemyError as exc:
        print(f"Database error ({type(exc).__name__}); check DATABASE_URL and that the database is reachable.", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace, settings: Settings) -> int:
    session_factory = get_session_factory(settings)
    engine = get_engine(settings)
    if session_factory is None or engine is None:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        return 2

    if args.command == "status":
        with session_factory() as session:
            print(get_status(session, settings, now_utc()).model_dump_json(indent=2))
        return 0

    if args.command == "sync-prices" and not args.dry_run and not settings.market_data_configured:
        print("INDIAN_API_KEY is not configured in backend/.env; price sync cannot run.", file=sys.stderr)
        return 2

    provider = build_provider(settings)
    try:
        if args.command == "sync-listings":
            outcome = sync_security_master(session_factory, engine, provider)
        else:
            outcome = sync_daily_prices(
                session_factory,
                engine,
                provider,
                settings,
                portfolio_id=args.portfolio_id,
                force=args.force,
                dry_run=args.dry_run,
            )
    except SyncAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    finally:
        provider.close()

    print(json.dumps(outcome.as_dict(), indent=2, default=str))
    return EXIT_CODES.get(outcome.status, 1)


if __name__ == "__main__":
    raise SystemExit(main())
