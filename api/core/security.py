"""Small authentication dependency for admin-only demo mutations."""

import os
import secrets

from fastapi import Header

from api.core.exceptions import ApiException, ErrorCode


async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_TOKEN")
    if not expected or not x_admin_token or not secrets.compare_digest(
        x_admin_token, expected
    ):
        raise ApiException(
            status_code=403,
            code=ErrorCode.FORBIDDEN,
            message="Admin access required",
        )
