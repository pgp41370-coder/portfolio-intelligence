"""FastAPI application factory.

Run locally from the backend directory:

    uv run uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import UploadSizeLimitMiddleware
from app.portfolios.csv_import import MAX_CSV_BYTES, MAX_CSV_SIZE_LABEL

# Room for multipart boundaries and the portfolio name field around the CSV file itself.
MULTIPART_OVERHEAD_BYTES = 16 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.state.settings = settings

    app.add_middleware(
        UploadSizeLimitMiddleware,
        max_body_bytes=MAX_CSV_BYTES + MULTIPART_OVERHEAD_BYTES,
        path_suffixes=("/csv-preview", "/csv-import"),
        message=f"CSV files must be {MAX_CSV_SIZE_LABEL} or smaller.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
