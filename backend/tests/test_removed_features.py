"""Regression coverage for the generic application after removing a domain."""


def test_default_builtin_registry_is_empty():
    from vassilflow.config.builtin_agents import get_builtin_agent, list_builtin_agents

    assert list_builtin_agents() == ()
    assert get_builtin_agent("office") is None


def test_gateway_has_no_removed_domain_routes():
    from app.gateway.app import create_app

    paths = {route.path for route in create_app().routes}
    assert not any(path.startswith("/api/office") for path in paths)
    assert "/api/actions" in paths
    assert "/api/agents" in paths
