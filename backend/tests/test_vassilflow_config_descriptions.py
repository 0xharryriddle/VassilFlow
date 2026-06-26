"""Static guards for VassilFlow-owned public config descriptions."""

from vassilflow.config.auth_config import AuthAppConfig, OIDCProviderConfig


def test_auth_config_descriptions_use_vassilflow_name() -> None:
    issuer_description = OIDCProviderConfig.model_fields["issuer"].description or ""
    auto_create_description = (
        OIDCProviderConfig.model_fields["auto_create_users"].description or ""
    )

    assert "realms/vassilflow" in issuer_description
    assert "VassilFlow user" in auto_create_description
    assert "VassilFlow app config" in (AuthAppConfig.__doc__ or "")
    assert "DeerFlow user" not in auto_create_description
    assert "DeerFlow app config" not in (AuthAppConfig.__doc__ or "")
