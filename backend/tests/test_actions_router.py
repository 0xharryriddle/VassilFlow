from __future__ import annotations

from pathlib import Path

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

import app.gateway.routers.actions as actions_router
from vassilflow.actions import FileActionStore


def _client() -> TestClient:
    app = make_authed_test_app()
    app.include_router(actions_router.router)
    return TestClient(app)


def test_actions_api_resolves_and_filters_current_user_records(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = FileActionStore(tmp_path / "alice", owner_user_id="alice")
    edit = store.start(
        operation="sample.edit",
        source="agent_run",
        assistant_id="sample",
        thread_id="thread-1",
        run_id="run-1",
        references=[{"kind": "sample.project", "id": "opj_1"}],
    )
    store.finish(
        edit["action_id"],
        status="succeeded",
        references=[{"kind": "sample.revision", "id": "orv_2"}],
    )
    store.start(
        operation="sample.project.render",
        source="user_api",
        references=[{"kind": "sample.project", "id": "opj_2"}],
    )
    monkeypatch.setattr(actions_router, "get_effective_user_id", lambda: "alice")
    monkeypatch.setattr(actions_router, "_store_for_user", lambda _user_id: store)

    with _client() as client:
        detail = client.get(f"/api/actions/{edit['action_id']}")
        filtered = client.get(
            "/api/actions",
            params={
                "resource_kind": "sample.project",
                "resource_id": "opj_1",
            },
        )

    assert detail.status_code == 200
    assert detail.json()["schema"] == "vassilflow.action.v1"
    assert detail.json()["run_id"] == "run-1"
    assert detail.json()["status"] == "succeeded"
    assert filtered.status_code == 200
    assert [item["action_id"] for item in filtered.json()["actions"]] == [edit["action_id"]]


def test_actions_api_does_not_resolve_another_users_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    alice = FileActionStore(tmp_path / "alice", owner_user_id="alice")
    bob = FileActionStore(tmp_path / "bob", owner_user_id="bob")
    action = alice.start(operation="sample.edit", source="user_api")
    monkeypatch.setattr(actions_router, "get_effective_user_id", lambda: "bob")
    monkeypatch.setattr(actions_router, "_store_for_user", lambda _user_id: bob)

    with _client() as client:
        response = client.get(f"/api/actions/{action['action_id']}")

    assert response.status_code == 404
