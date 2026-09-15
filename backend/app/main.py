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
from app.core.middleware import ReadOnlyApiMiddleware, UploadSizeLimitMiddleware
from app.portfolios.csv_import import MAX_CSV_BYTES, MAX_CSV_SIZE_LABEL

# Room for multipart boundaries and the portfolio name field around the CSV file itself.
MULTIPART_OVERHEAD_BYTES = 16 * 1024

READ_ONLY_MESSAGE = (
    "This public demo is read-only. Portfolios and holdings cannot be created, changed or uploaded here; "
    "run the application locally to use your own portfolios."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    # Interactive documentation and the OpenAPI schema are served outside production only.
    docs = settings.api_docs_enabled
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings

    # Middleware added last runs first: CORS, then the read-only guard, then the upload limit.
    app.add_middleware(
        UploadSizeLimitMiddleware,
        max_body_bytes=MAX_CSV_BYTES + MULTIPART_OVERHEAD_BYTES,
        path_suffixes=("/csv-preview", "/csv-import"),
        message=f"CSV files must be {MAX_CSV_SIZE_LABEL} or smaller.",
    )
    if not settings.write_api_enabled:
        app.add_middleware(ReadOnlyApiMiddleware, message=READ_ONLY_MESSAGE)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins or [],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Accept", "Content-Type"],
    )
    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
