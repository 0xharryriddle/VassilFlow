import json
from dataclasses import fields, is_dataclass
from inspect import signature
from pathlib import Path

from vassilflow import boundary

CONTRACT_PATH = Path(__file__).parents[2] / "contracts" / "vassilflow_boundary_contract.json"


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_vassilflow_boundary_contract_is_versioned_json():
    contract = _load_contract()

    assert contract["version"] == 1
    assert "description" in contract
    assert "entities" in contract


def test_vassilflow_boundary_contract_declares_core_entities():
    contract = _load_contract()

    assert set(contract["entities"]) >= {
        "Session",
        "Run",
        "TraceStep",
        "ToolSpec",
        "PolicyDecision",
        "ApprovalRequest",
        "CompletionEvidence",
    }


def test_vassilflow_boundary_contract_declares_policy_decisions():
    contract = _load_contract()

    assert contract["status_values"]["policy_decision"] == [
        "allow",
        "deny",
        "ask",
        "redact",
        "sanitize",
        "escalate",
    ]


def test_vassilflow_boundary_contract_has_completion_events():
    contract = _load_contract()

    assert {"verification.completed", "run.completed", "run.failed"} <= set(contract["event_types"])


def test_vassilflow_boundary_enums_match_contract_status_values():
    contract = _load_contract()

    assert boundary.BOUNDARY_CONTRACT_VERSION == contract["version"]
    assert [status.value for status in boundary.SessionStatus] == contract["status_values"]["session"]
    assert [status.value for status in boundary.RunStatus] == contract["status_values"]["run"]
    assert [status.value for status in boundary.ApprovalStatus] == contract["status_values"]["approval"]
    assert [decision.value for decision in boundary.PolicyDecisionValue] == contract["status_values"]["policy_decision"]
    assert [event.value for event in boundary.EventType] == contract["event_types"]


def test_vassilflow_boundary_entities_match_contract_fields():
    contract = _load_contract()

    assert set(boundary.ENTITY_TYPES) == set(contract["entities"])
    for entity_name, entity_class in boundary.ENTITY_TYPES.items():
        assert is_dataclass(entity_class), entity_name
        expected_fields = set(contract["entities"][entity_name]["required_fields"])
        expected_fields.update(contract["entities"][entity_name]["optional_fields"])
        assert {field.name for field in fields(entity_class)} == expected_fields


def test_vassilflow_facade_reexports_current_runtime_without_renaming_deerflow():
    from vassilflow import create_vassilflow_agent
    from vassilflow.agents import create_deerflow_agent as facade_create_deerflow_agent
    from vassilflow.agents import create_vassilflow_agent as facade_create_vassilflow_agent
    from vassilflow.client import VassilFlowClient
    from vassilflow.models import create_chat_model as facade_create_chat_model
    from vassilflow.models import factory as facade_model_factory
    from vassilflow.runtime import RunManager as VassilFlowRunManager
    from vassilflow.runtime import RuntimeRunStatus

    from deerflow.agents import create_deerflow_agent
    from deerflow.client import DeerFlowClient
    from deerflow.models import create_chat_model
    from deerflow.runtime import RunManager
    from deerflow.runtime import RunStatus as DeerFlowRunStatus

    assert issubclass(VassilFlowClient, DeerFlowClient)
    assert VassilFlowClient.__name__ == "VassilFlowClient"
    assert VassilFlowRunManager is RunManager
    assert RuntimeRunStatus is DeerFlowRunStatus
    assert create_vassilflow_agent.__name__ == "create_vassilflow_agent"
    assert facade_create_vassilflow_agent.__name__ == "create_vassilflow_agent"
    assert signature(facade_create_vassilflow_agent) == signature(create_deerflow_agent)
    assert facade_create_deerflow_agent is create_deerflow_agent
    assert facade_create_chat_model is create_chat_model
    assert facade_model_factory.create_chat_model is create_chat_model


def test_vassilflow_config_facade_exports_current_config_api(monkeypatch):
    import vassilflow.config as facade_config

    from deerflow.config.app_config import AppConfig, get_app_config, reload_app_config
    from deerflow.config.paths import Paths, get_paths
    from deerflow.config.title_config import (
        TitleConfig,
        get_title_config,
        set_title_config,
    )

    assert facade_config.AppConfig is AppConfig
    assert facade_config.Paths is Paths
    assert facade_config.TitleConfig is TitleConfig
    assert facade_config.get_app_config is get_app_config
    assert facade_config.get_paths is get_paths
    assert facade_config.get_title_config is get_title_config
    assert facade_config.reload_app_config is reload_app_config
    assert facade_config.set_title_config is set_title_config

    monkeypatch.setattr(facade_config, "reload_app_config", lambda config_path=None: ("loaded", config_path))

    assert facade_config.load_config("/tmp/config.yaml") == ("loaded", "/tmp/config.yaml")
