from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("compose_name", "app_network", "private_network"),
    [
        ("docker-compose-dev.yaml", "vassilflow-dev", "vassilflow-office"),
        ("docker-compose.yaml", "vassilflow", "vassilflow-office"),
    ],
)
def test_office_renderer_is_isolated_from_project_and_secrets(
    compose_name: str,
    app_network: str,
    private_network: str,
) -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker" / compose_name).read_text(encoding="utf-8"))
    renderer = compose["services"]["office-renderer"]
    proxy = compose["services"]["office-renderer-proxy"]
    gateway = compose["services"]["gateway"]

    assert renderer["read_only"] is True
    assert renderer["cap_drop"] == ["ALL"]
    assert renderer["security_opt"] == ["no-new-privileges:true"]
    assert renderer["cpus"] == 1.0
    assert "volumes" not in renderer
    assert "env_file" not in renderer
    assert renderer["networks"] == [private_network]
    assert compose["networks"][private_network]["internal"] is True
    assert proxy["networks"] == [private_network, app_network]
    assert proxy["read_only"] is True
    assert proxy["cap_drop"] == ["ALL"]
    assert "env_file" not in proxy
    assert private_network not in gateway["networks"]
    assert gateway["depends_on"]["office-renderer-proxy"]["condition"] == "service_healthy"
    assert "VASSILFLOW_OFFICE_RENDERER_URL=http://office-renderer-proxy:8004" in gateway["environment"]


def test_development_renderer_port_is_loopback_only() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker" / "docker-compose-dev.yaml").read_text(encoding="utf-8"))

    assert "ports" not in compose["services"]["office-renderer"]
    assert compose["services"]["office-renderer-proxy"]["ports"] == ["127.0.0.1:${VASSILFLOW_OFFICE_RENDERER_PORT:-8003}:8004"]


def test_production_renderer_does_not_publish_a_host_port() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker" / "docker-compose.yaml").read_text(encoding="utf-8"))

    assert "ports" not in compose["services"]["office-renderer"]
    assert "ports" not in compose["services"]["office-renderer-proxy"]


def test_renderer_proxy_exposes_only_health_and_office_render_routes() -> None:
    config = (REPO_ROOT / "docker" / "office-renderer" / "proxy.conf").read_text(encoding="utf-8")

    assert "location = /health" in config
    assert "location = /v1/render/docx" in config
    assert "location = /v1/render/xlsx" in config
    assert "location = /v1/render/pptx" in config
    assert "location /" in config
    assert "proxy_pass http://office_renderer_backend" in config
    assert "gateway" not in config


def test_renderer_image_includes_writer_calc_and_impress() -> None:
    dockerfile = (REPO_ROOT / "docker" / "office-renderer" / "Dockerfile").read_text(encoding="utf-8")

    assert "libreoffice-writer" in dockerfile
    assert "libreoffice-calc" in dockerfile
    assert "libreoffice-impress" in dockerfile
