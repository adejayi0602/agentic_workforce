import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from workforce_api import __version__
from workforce_api.auth import dev_routes
from workforce_api.auth.dev_issuer import DevTokenIssuer
from workforce_api.auth.tokens import KeyResolver, TokenValidator, jwks_key_resolver
from workforce_api.config import Settings, get_settings
from workforce_api.correlation import (
    CORRELATION_HEADER,
    CorrelationIdLogFilter,
    CorrelationIdMiddleware,
)
from workforce_api.db import Database
from workforce_api.errors import register_error_handlers
from workforce_api.modules.audit import routes as audit_routes
from workforce_api.modules.documents import routes as document_routes
from workforce_api.modules.identity import routes as identity_routes
from workforce_api.modules.projects import routes as project_routes
from workforce_api.routes import health
from workforce_api.storage import ObjectStore
from workforce_api.workflows import WorkflowStarter

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdLogFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(correlation_id)s] %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def _configure_auth(app: FastAPI, settings: Settings) -> None:
    key_resolver: KeyResolver
    if settings.auth_mode == "dev":
        issuer = DevTokenIssuer(issuer=settings.auth_issuer, audience=settings.auth_audience)
        app.state.dev_issuer = issuer
        key_resolver = issuer.resolve_key
        logger.warning("Development authentication is enabled (env=%s).", settings.env)
    else:
        key_resolver = jwks_key_resolver(settings.jwks_url)
    app.state.token_validator = TokenValidator(
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
        key_resolver=key_resolver,
        clock_skew_seconds=settings.auth_clock_skew_seconds,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.log_level)
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await database.dispose()
        await app.state.workflows.close()

    app = FastAPI(
        title="Agentic IT Workforce API",
        version=__version__,
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.object_store = ObjectStore.from_settings(settings)
    app.state.workflows = WorkflowStarter(settings)
    _configure_auth(app, settings)

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
    v1.include_router(identity_routes.router)
    v1.include_router(audit_routes.router)
    v1.include_router(project_routes.router)
    v1.include_router(document_routes.router)
    if settings.auth_mode == "dev":
        v1.include_router(dev_routes.router)
    app.include_router(v1)
    return app


app = create_app()
