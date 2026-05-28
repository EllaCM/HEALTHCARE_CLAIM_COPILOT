"""FastAPI application factory.

Run with:
    uvicorn src.api.main:app --reload --port 8080
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scripts.cpt_definitions_adapter import CPTDefinitionsAdapter
from src.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from src.api.routers import (
    chat,
    codes,
    cpt,
    encounters,
    health,
    ingest,
    pipeline,
)
from src.api.settings import load_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = load_settings()
    app.state.cpt_adapter = CPTDefinitionsAdapter(
        yaml_path=app.state.settings.cpt_definitions_path,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Healthcare Claim Copilot API",
        version="0.1.0",
        lifespan=lifespan,
    )

    settings = load_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(health.router)
    app.include_router(encounters.router)
    app.include_router(codes.router)
    app.include_router(pipeline.router)
    app.include_router(chat.router)
    app.include_router(ingest.router)
    app.include_router(cpt.router)

    return app


app = create_app()
