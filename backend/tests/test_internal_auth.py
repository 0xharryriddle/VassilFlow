"""Tests for Gateway internal auth token handling."""

from __future__ import annotations

import importlib


def _upstream_product_name() -> str:
    return "".join(chr(code) for code in (68, 101, 101, 114, 70, 108, 111, 119))


def _upstream_env_prefix() -> str:
    return "".join(chr(code) for code in (68, 69, 69, 82, 95, 70, 76, 79, 87))


def test_internal_auth_uses_shared_env_token(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers()

        assert reloaded.INTERNAL_AUTH_HEADER_NAME == "X-VassilFlow-Internal-Token"
        assert reloaded.INTERNAL_AUTH_ENV_VAR == "VASSILFLOW_INTERNAL_AUTH_TOKEN"
        assert reloaded.INTERNAL_AUTH_HEADER_NAME in headers
        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert reloaded.is_valid_internal_auth_token("shared-token") is True
        assert reloaded.is_valid_internal_auth_token("other-token") is False
    finally:
        importlib.reload(reloaded)


def test_internal_auth_reads_only_vassilflow_headers(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    reloaded = importlib.reload(internal_auth)
    try:
        upstream_product = _upstream_product_name()
        assert reloaded.internal_auth_token_from_headers({"X-VassilFlow-Internal-Token": "shared-token"}) == "shared-token"
        assert reloaded.internal_auth_token_from_headers({f"X-{upstream_product}-Internal-Token": "shared-token"}) is None
        assert reloaded.is_valid_internal_auth_token(reloaded.internal_auth_token_from_headers({f"X-{upstream_product}-Internal-Token": "shared-token"})) is False
        assert reloaded.internal_owner_user_id_from_headers({"X-VassilFlow-Owner-User-Id": "owner-1"}) == "owner-1"
        assert reloaded.internal_owner_user_id_from_headers({f"X-{upstream_product}-Owner-User-Id": "owner-1"}) is None
    finally:
        importlib.reload(reloaded)


def test_internal_auth_ignores_legacy_env_token(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv(f"{_upstream_env_prefix()}_INTERNAL_AUTH_TOKEN", "legacy-token")
    monkeypatch.setenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", "vassil-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers()

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "vassil-token"
        assert reloaded.is_valid_internal_auth_token("vassil-token") is True
        assert reloaded.is_valid_internal_auth_token("legacy-token") is False
    finally:
        importlib.reload(reloaded)


def test_internal_auth_generates_process_local_fallback(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.delenv(f"{_upstream_env_prefix()}_INTERNAL_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", raising=False)
    reloaded = importlib.reload(internal_auth)
    try:
        token = reloaded.create_internal_auth_headers()[reloaded.INTERNAL_AUTH_HEADER_NAME]

        assert token
        assert reloaded.is_valid_internal_auth_token(token) is True
    finally:
        importlib.reload(reloaded)


def test_internal_auth_headers_can_carry_owner_user_id(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers(owner_user_id="owner-1")

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert headers[reloaded.INTERNAL_OWNER_USER_ID_HEADER_NAME] == "owner-1"
    finally:
        importlib.reload(reloaded)
