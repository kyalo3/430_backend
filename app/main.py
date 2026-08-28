"""Sustainashare API application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import get_settings
from app.database import client, ensure_indexes
from app.routes import (
    contact,
    donation_request,
    donations,
    donor,
    recipient,
    reviews,
    user,
    volunteer,
)
from app.routes import auth_routes, fulfilment, health, impact, matching_routes, notifications, organisations, integrations, platform, reference


async def _warmup_reference() -> None:
    try:
        from app.services.opendata import sync_world_bank

        await sync_world_bank(force=False)
    except Exception:
        # Bundled counties/categories still work if World Bank is unreachable.
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Validate settings eagerly
    _ = settings.secret_key
    await ensure_indexes()
    # Ping Mongo
    await client.admin.command("ping")
    if settings.feature_world_bank:
        app.state.reference_sync = asyncio.create_task(_warmup_reference())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Trusted resource-redistribution and impact-visibility API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_host_list + ["testserver"],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", settings.csrf_header_name, "X-Request-ID"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        req_id = request.headers.get("X-Request-ID")
        if req_id:
            response.headers["X-Request-ID"] = req_id
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"detail": "Internal server error", "type": "server_error"})

    prefix = settings.api_prefix

    # Versioned API
    for router in (
        auth_routes.router,
        health.router,
        impact.router,
        matching_routes.router,
        platform.router,
        user.router,
        donor.router,
        donations.router,
        recipient.router,
        volunteer.router,
        reviews.router,
        contact.router,
        donation_request.router,
        fulfilment.router,
        notifications.router,
        organisations.router,
        integrations.router,
        reference.router,
    ):
        app.include_router(router, prefix=prefix)

    # Compatibility aliases (legacy unversioned paths used by existing frontend)
    for router in (
        auth_routes.compat_router,
        user.router,
        donor.router,
        donations.router,
        recipient.router,
        volunteer.router,
        reviews.router,
        contact.router,
        donation_request.router,
        health.router,
        impact.router,
        matching_routes.router,
        platform.router,
        fulfilment.router,
        notifications.router,
        organisations.router,
        integrations.router,
        reference.router,
    ):
        app.include_router(router)

    return app


app = create_app()
