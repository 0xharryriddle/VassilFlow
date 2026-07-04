import json
from dataclasses import fields, is_dataclass
from importlib import import_module
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
    assert "legacy implementation can remain the v0 runtime" in contract["description"]
    assert "DeerFlow can remain the v0 runtime" not in contract["description"]


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


def test_vassilflow_package_exports_current_runtime_api():
    from vassilflow import create_vassilflow_agent
    from vassilflow.agents import create_vassilflow_agent as package_create_vassilflow_agent
    from vassilflow.agents.factory import (
        create_vassilflow_agent as factory_create_vassilflow_agent,
    )
    from vassilflow.client import VassilFlowClient
    from vassilflow.models import create_chat_model
    from vassilflow.models import create_chat_model as package_create_chat_model
    from vassilflow.models import factory as model_factory
    from vassilflow.runtime import RunManager, RunStatus, make_store, serialize_channel_values_for_api
    from vassilflow.runtime import RunManager as VassilFlowRunManager
    from vassilflow.runtime import RunStatus as VassilFlowRunStatus
    from vassilflow.runtime import make_store as package_make_store
    from vassilflow.runtime import serialize_channel_values_for_api as package_serialize_api

    vassilflow_store = import_module("vassilflow.runtime.store")
    vassilflow_store_provider = import_module("vassilflow.runtime.store.provider")

    assert VassilFlowClient.__name__ == "VassilFlowClient"
    assert VassilFlowRunManager is RunManager
    assert VassilFlowRunStatus is RunStatus
    assert package_make_store is make_store
    assert package_serialize_api is serialize_channel_values_for_api
    assert create_vassilflow_agent.__name__ == "create_vassilflow_agent"
    assert package_create_vassilflow_agent.__name__ == "create_vassilflow_agent"
    assert signature(package_create_vassilflow_agent) == signature(factory_create_vassilflow_agent)
    assert package_create_vassilflow_agent is factory_create_vassilflow_agent
    assert package_create_chat_model is create_chat_model
    assert model_factory.create_chat_model is create_chat_model
    assert vassilflow_store.make_store is make_store
    assert vassilflow_store_provider.get_store is vassilflow_store.get_store


def test_vassilflow_config_package_exports_current_config_api(monkeypatch):
    import vassilflow.config as package_config
    from vassilflow.config.app_config import AppConfig, get_app_config, reload_app_config
    from vassilflow.config.paths import Paths, get_paths
    from vassilflow.config.title_config import (
        TitleConfig,
        get_title_config,
        set_title_config,
    )

    assert package_config.AppConfig is AppConfig
    assert package_config.Paths is Paths
    assert package_config.TitleConfig is TitleConfig
    assert package_config.get_app_config is get_app_config
    assert package_config.get_paths is get_paths
    assert package_config.get_title_config is get_title_config
    assert package_config.reload_app_config is reload_app_config
    assert package_config.set_title_config is set_title_config

    monkeypatch.setattr(package_config, "reload_app_config", lambda config_path=None: ("loaded", config_path))

    assert package_config.load_config("/tmp/config.yaml") == ("loaded", "/tmp/config.yaml")


def test_vassilflow_config_deep_imports_alias_current_config_modules():
    from vassilflow.config.app_config import AppConfig, get_app_config
    from vassilflow.config.app_config import AppConfig as FacadeAppConfig
    from vassilflow.config.app_config import get_app_config as facade_get_app_config
    from vassilflow.config.paths import Paths, get_paths
    from vassilflow.config.paths import Paths as FacadePaths
    from vassilflow.config.paths import get_paths as facade_get_paths
    from vassilflow.config.title_config import TitleConfig
    from vassilflow.config.title_config import TitleConfig as FacadeTitleConfig

    assert FacadeAppConfig is AppConfig
    assert facade_get_app_config is get_app_config
    assert FacadePaths is Paths
    assert facade_get_paths is get_paths
    assert FacadeTitleConfig is TitleConfig


def test_vassilflow_runtime_deep_imports_alias_current_runtime_modules():
    from vassilflow.runtime.runs.naming import resolve_root_run_name
    from vassilflow.runtime.runs.naming import (
        resolve_root_run_name as facade_resolve_root_run_name,
    )
    from vassilflow.runtime.user_context import get_effective_user_id
    from vassilflow.runtime.user_context import (
        get_effective_user_id as facade_get_effective_user_id,
    )

    assert facade_resolve_root_run_name is resolve_root_run_name
    assert facade_get_effective_user_id is get_effective_user_id


def test_vassilflow_public_package_aliases_resolve_current_implementation_modules():
    module_names = [
        "vassilflow.agents.features",
        "vassilflow.sandbox.middleware",
        "vassilflow.sandbox.local",
        "vassilflow.sandbox.tools",
        "vassilflow.community.tavily.tools",
        "vassilflow.skills.installer",
        "vassilflow.uploads.manager",
    ]

    for facade_name in module_names:
        facade_module = import_module(facade_name)
        implementation_name = facade_name.replace("vassilflow.", "vassilflow.", 1)
        assert facade_module is import_module(implementation_name)
