import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from workforce_api import __version__
from workforce_api.config import get_settings
from workforce_api.correlation import (
    CORRELATION_HEADER,
    CorrelationIdLogFilter,
    CorrelationIdMiddleware,
)
from workforce_api.errors import register_error_handlers
from workforce_api.routes import health


def _configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdLogFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(correlation_id)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title="Agentic IT Workforce API",
        version=__version__,
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[CORRELATION_HEADER],
    )
    # Added last so it runs first and every response, including errors, gets the header.
    app.add_middleware(CorrelationIdMiddleware)
    register_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(health.router)
    app.include_router(v1)
    return app


app = create_app()
