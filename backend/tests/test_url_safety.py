"""Tests for shared community web URL safety checks."""

from __future__ import annotations

import ipaddress

from vassilflow.community.url_safety import validate_public_http_url


def test_validate_public_http_url_rejects_non_http_scheme():
    assert validate_public_http_url("file:///etc/passwd") == "Error: Only http:// and https:// URLs are supported"


def test_validate_public_http_url_rejects_loopback_literal():
    result = validate_public_http_url("http://127.0.0.1:8080/admin")

    assert result is not None
    assert "Refusing to fetch" in result


def test_validate_public_http_url_rejects_private_dns_result():
    result = validate_public_http_url(
        "https://internal.example",
        resolver=lambda _hostname: [ipaddress.ip_address("10.0.0.5")],
    )

    assert result is not None
    assert "private" in result


def test_validate_public_http_url_allows_public_dns_result():
    result = validate_public_http_url(
        "https://example.com",
        resolver=lambda _hostname: [ipaddress.ip_address("93.184.216.34")],
    )

    assert result is None


def test_validate_public_http_url_allow_private_addresses_opt_out():
    assert validate_public_http_url("http://127.0.0.1:8080", allow_private_addresses=True) is None
