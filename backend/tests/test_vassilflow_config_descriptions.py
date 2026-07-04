"""Static guards for VassilFlow-owned public config descriptions."""

import vassilflow.config.safety_finish_reason_config as safety_config_module
import vassilflow.persistence as persistence_module
from vassilflow.config.app_config import AppConfig, get_app_config
from vassilflow.config.auth_config import AuthAppConfig, OIDCProviderConfig
from vassilflow.config.extensions_config import ExtensionsConfig
from vassilflow.config.memory_config import MemoryConfig
from vassilflow.persistence.base import Base


def test_auth_config_descriptions_use_vassilflow_name() -> None:
    issuer_description = OIDCProviderConfig.model_fields["issuer"].description or ""
    auto_create_description = OIDCProviderConfig.model_fields["auto_create_users"].description or ""

    assert "realms/vassilflow" in issuer_description
    assert "VassilFlow user" in auto_create_description
    assert "VassilFlow app config" in (AuthAppConfig.__doc__ or "")


def test_runtime_config_docstrings_use_vassilflow_primary_name() -> None:
    app_resolver_doc = AppConfig.resolve_env_variables.__doc__ or ""
    extensions_resolver_doc = ExtensionsConfig.resolve_env_variables.__doc__ or ""

    assert "VassilFlow" in app_resolver_doc
    assert "VassilFlow" in extensions_resolver_doc
    assert "legacy upstream aliases" not in app_resolver_doc
    assert "legacy upstream aliases" not in extensions_resolver_doc
    assert "Get the VassilFlow config instance" in (get_app_config.__doc__ or "")


def test_persistence_docstrings_use_vassilflow_package() -> None:
    assert "VassilFlow ORM models" in (Base.__doc__ or "")
    assert "from vassilflow.persistence import" in (persistence_module.__doc__ or "")


def test_memory_storage_default_uses_vassilflow_package() -> None:
    assert MemoryConfig.model_fields["storage_class"].default == "vassilflow.agents.memory.storage.FileMemoryStorage"


def test_safety_config_docstring_uses_vassilflow_reflection_package() -> None:
    doc = safety_config_module.__doc__ or ""

    assert "vassilflow.reflection.resolve_variable" in doc
