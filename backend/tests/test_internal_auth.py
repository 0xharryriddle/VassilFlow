"""Tests for Gateway internal auth token handling."""

from __future__ import annotations

import importlib


def test_internal_auth_uses_shared_env_token(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers()

        assert reloaded.INTERNAL_AUTH_HEADER_NAME == "X-VassilFlow-Internal-Token"
        assert reloaded.LEGACY_INTERNAL_AUTH_HEADER_NAME == "X-DeerFlow-Internal-Token"
        assert reloaded.INTERNAL_AUTH_ENV_VAR == "VASSILFLOW_INTERNAL_AUTH_TOKEN"
        assert reloaded.LEGACY_INTERNAL_AUTH_ENV_VAR == "DEER_FLOW_INTERNAL_AUTH_TOKEN"
        assert reloaded.INTERNAL_AUTH_HEADER_NAME in headers
        assert reloaded.LEGACY_INTERNAL_AUTH_HEADER_NAME not in headers
        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert reloaded.is_valid_internal_auth_token("shared-token") is True
        assert reloaded.is_valid_internal_auth_token("other-token") is False
    finally:
        monkeypatch.delenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)


def test_internal_auth_reads_current_and_legacy_headers(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", "shared-token")
    monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
    reloaded = importlib.reload(internal_auth)
    try:
        assert reloaded.internal_auth_token_from_headers({"X-VassilFlow-Internal-Token": "shared-token"}) == "shared-token"
        assert reloaded.internal_auth_token_from_headers({"X-DeerFlow-Internal-Token": "shared-token"}) == "shared-token"
        assert reloaded.is_valid_internal_auth_token(reloaded.internal_auth_token_from_headers({"X-DeerFlow-Internal-Token": "shared-token"})) is True
        assert reloaded.internal_owner_user_id_from_headers({"X-VassilFlow-Owner-User-Id": "owner-1"}) == "owner-1"
        assert reloaded.internal_owner_user_id_from_headers({"X-DeerFlow-Owner-User-Id": "owner-1"}) == "owner-1"
    finally:
        monkeypatch.delenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)


def test_internal_auth_prefers_vassilflow_env_token(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "legacy-token")
    monkeypatch.setenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", "vassil-token")
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers()

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "vassil-token"
        assert reloaded.is_valid_internal_auth_token("vassil-token") is True
        assert reloaded.is_valid_internal_auth_token("legacy-token") is False
    finally:
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)


def test_internal_auth_generates_process_local_fallback(monkeypatch):
    import app.gateway.internal_auth as internal_auth

    monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
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
    monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
    reloaded = importlib.reload(internal_auth)
    try:
        headers = reloaded.create_internal_auth_headers(owner_user_id="owner-1")

        assert headers[reloaded.INTERNAL_AUTH_HEADER_NAME] == "shared-token"
        assert headers[reloaded.INTERNAL_OWNER_USER_ID_HEADER_NAME] == "owner-1"
    finally:
        monkeypatch.delenv("VASSILFLOW_INTERNAL_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", raising=False)
        importlib.reload(reloaded)
