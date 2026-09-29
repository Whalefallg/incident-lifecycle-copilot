"""Stable API error contract and domain-to-HTTP exception mapping."""

import logging
from enum import Enum
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from conversation.repository import (
    ConcurrentConversationUpdate,
    ConversationAlreadyExists,
    IdempotencyKeyMismatch,
    RequestInProgress,
)

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONVERSATION_CONFLICT = "CONVERSATION_CONFLICT"
    IDEMPOTENCY_MISMATCH = "IDEMPOTENCY_MISMATCH"
    REQUEST_IN_PROGRESS = "REQUEST_IN_PROGRESS"
    INCIDENT_ALREADY_EXISTS = "INCIDENT_ALREADY_EXISTS"
    RAG_UNAVAILABLE = "RAG_UNAVAILABLE"
    AGENT_EXECUTION_ERROR = "AGENT_EXECUTION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ApiException(HTTPException):
    def __init__(
        self,
        *,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message
        self.details = details or {}


class BusinessException(ApiException):
    """Backward-compatible application error used by legacy routes."""

    def __init__(self, message: str):
        super().__init__(status_code=400, code=ErrorCode.VALIDATION_ERROR, message=message)


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or getattr(request.state, "session_id", "unknown")


def _response(
    request: Request,
    *,
    status_code: int,
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=code, message=message, request_id=_request_id(request), details=details or {}
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


async def api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
    logger.warning("API error %s: %s", exc.code, exc.message)
    return _response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _response(
        request,
        status_code=422,
        code=ErrorCode.VALIDATION_ERROR,
        message="Request validation failed",
        details={"errors": exc.errors()},
    )


async def repository_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ConcurrentConversationUpdate):
        return _response(
            request,
            status_code=409,
            code=ErrorCode.CONVERSATION_CONFLICT,
            message="Incident was updated by another request",
        )
    if isinstance(exc, IdempotencyKeyMismatch):
        return _response(
            request,
            status_code=409,
            code=ErrorCode.IDEMPOTENCY_MISMATCH,
            message="Request ID was already used with a different payload",
        )
    if isinstance(exc, RequestInProgress):
        return _response(
            request,
            status_code=409,
            code=ErrorCode.REQUEST_IN_PROGRESS,
            message="A request with this ID is still in progress",
        )
    if isinstance(exc, ConversationAlreadyExists):
        return _response(
            request,
            status_code=409,
            code=ErrorCode.INCIDENT_ALREADY_EXISTS,
            message="An incident with this ID already exists",
        )
    raise exc


async def incident_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return _response(
        request,
        status_code=404,
        code=ErrorCode.NOT_FOUND,
        message=f"Incident '{exc}' was not found",
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API exception", exc_info=exc)
    return _response(
        request,
        status_code=500,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected server error occurred",
    )
