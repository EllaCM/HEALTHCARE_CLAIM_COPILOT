"""Structured error model — every non-2xx response carries `{error: {code, message, details?}}`."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str, details: Any = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def encounter_not_found(encounter_id: str) -> ApiError:
    return ApiError(
        status_code=404,
        code="encounter_not_found",
        message=f"Encounter '{encounter_id}' not found.",
        details={"encounter_id": encounter_id},
    )


def upstream_llm_error(detail: str) -> ApiError:
    return ApiError(status_code=502, code="upstream_llm_error", message=detail)


def missing_anthropic_key() -> ApiError:
    return ApiError(
        status_code=401,
        code="missing_anthropic_key",
        message="Anthropic API key missing. Send it via 'Authorization: Bearer <key>' or set ANTHROPIC_API_KEY server-side.",
    )


def validation_failed(errors: list[str]) -> ApiError:
    return ApiError(
        status_code=422,
        code="payload_validation_failed",
        message="Encounter payload failed schema validation.",
        details={"errors": errors},
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": str(exc), "details": None}},
    )
