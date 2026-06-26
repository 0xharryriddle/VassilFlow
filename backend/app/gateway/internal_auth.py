"""Authentication for trusted Gateway internal callers."""

from __future__ import annotations

import secrets
from types import SimpleNamespace
from typing import Any

from deerflow.config.env_aliases import first_env_value
from deerflow.runtime.user_context import DEFAULT_USER_ID

INTERNAL_AUTH_HEADER_NAME = "X-VassilFlow-Internal-Token"
LEGACY_INTERNAL_AUTH_HEADER_NAME = "X-DeerFlow-Internal-Token"
INTERNAL_OWNER_USER_ID_HEADER_NAME = "X-VassilFlow-Owner-User-Id"
LEGACY_INTERNAL_OWNER_USER_ID_HEADER_NAME = "X-DeerFlow-Owner-User-Id"
INTERNAL_AUTH_ENV_VAR = "VASSILFLOW_INTERNAL_AUTH_TOKEN"
LEGACY_INTERNAL_AUTH_ENV_VAR = "DEER_FLOW_INTERNAL_AUTH_TOKEN"
INTERNAL_SYSTEM_ROLE = "internal"


def _load_internal_auth_token() -> str:
    token = first_env_value((INTERNAL_AUTH_ENV_VAR, LEGACY_INTERNAL_AUTH_ENV_VAR))
    if token:
        return token
    return secrets.token_urlsafe(32)


_INTERNAL_AUTH_TOKEN = _load_internal_auth_token()


def create_internal_auth_headers(*, owner_user_id: str | None = None) -> dict[str, str]:
    """Return headers that authenticate trusted Gateway internal calls."""
    headers = {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}
    if owner_user_id:
        headers[INTERNAL_OWNER_USER_ID_HEADER_NAME] = owner_user_id
    return headers


def internal_auth_token_from_headers(headers: Any) -> str | None:
    """Return the internal auth token from current or legacy headers."""

    return headers.get(INTERNAL_AUTH_HEADER_NAME) or headers.get(LEGACY_INTERNAL_AUTH_HEADER_NAME)


def internal_owner_user_id_from_headers(headers: Any) -> str | None:
    """Return the owner override from current or legacy internal headers."""

    return headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME) or headers.get(LEGACY_INTERNAL_OWNER_USER_ID_HEADER_NAME)


def is_valid_internal_auth_token(token: str | None) -> bool:
    """Return True when *token* matches this Gateway worker's internal token."""
    return bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


def get_internal_user():
    """Return the synthetic user used for trusted internal channel calls."""
    return SimpleNamespace(id=DEFAULT_USER_ID, system_role=INTERNAL_SYSTEM_ROLE)


def get_trusted_internal_owner_user_id(request: Any) -> str | None:
    """Return the owner override for a trusted internal request, if present.

    The header is ignored for normal browser/API callers. It is only honored
    after ``AuthMiddleware`` has validated the internal auth token and stamped
    the synthetic internal user onto ``request.state.user``.
    """
    user = getattr(getattr(request, "state", None), "user", None)
    if getattr(user, "system_role", None) != INTERNAL_SYSTEM_ROLE:
        return None

    owner_user_id = internal_owner_user_id_from_headers(request.headers)
    if not owner_user_id:
        return None
    owner_user_id = owner_user_id.strip()
    return owner_user_id or None
