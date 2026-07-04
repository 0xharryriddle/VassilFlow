"""Tests for scripts/load_memory_sample.py."""

from __future__ import annotations

import load_memory_sample


def test_default_target_prefers_vassilflow_home(tmp_path, monkeypatch):
    current_home = tmp_path / "current-home"
    legacy_home = tmp_path / "legacy-home"
    monkeypatch.setenv("VASSILFLOW_HOME", str(current_home))
    monkeypatch.setenv("DEER_FLOW_HOME", str(legacy_home))

    assert load_memory_sample.default_target(tmp_path) == current_home / "memory.json"


def test_default_target_ignores_legacy_home(tmp_path, monkeypatch):
    legacy_home = tmp_path / "legacy-home"
    monkeypatch.delenv("VASSILFLOW_HOME", raising=False)
    monkeypatch.setenv("DEER_FLOW_HOME", str(legacy_home))

    assert load_memory_sample.default_target(tmp_path) == tmp_path / "backend" / ".vassilflow" / "memory.json"


def test_default_target_prefers_existing_current_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("VASSILFLOW_HOME", raising=False)
    monkeypatch.delenv("DEER_FLOW_HOME", raising=False)
    current_home = tmp_path / "backend" / ".vassilflow"
    legacy_home = tmp_path / "backend" / ".deer-flow"
    current_home.mkdir(parents=True)
    legacy_home.mkdir(parents=True)

    assert load_memory_sample.default_target(tmp_path) == current_home / "memory.json"


def test_default_target_ignores_existing_legacy_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("VASSILFLOW_HOME", raising=False)
    monkeypatch.delenv("DEER_FLOW_HOME", raising=False)
    legacy_home = tmp_path / "backend" / ".deer-flow"
    legacy_home.mkdir(parents=True)

    assert load_memory_sample.default_target(tmp_path) == tmp_path / "backend" / ".vassilflow" / "memory.json"
