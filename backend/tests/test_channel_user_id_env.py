"""Tests for exposing IM channel sender identity to sandbox commands."""

from __future__ import annotations

from types import SimpleNamespace

from vassilflow.sandbox.tools import (
    CHANNEL_USER_ID_ENV,
    _channel_identity_prefix,
    bash_tool,
)

_THREAD_DATA = {
    "workspace_path": "/tmp/vassilflow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/vassilflow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/vassilflow/threads/t1/user-data/outputs",
}


def _aio_runtime(context: dict) -> SimpleNamespace:
    return SimpleNamespace(
        state={"sandbox": {"sandbox_id": "aio-sandbox-1"}, "thread_data": _THREAD_DATA.copy()},
        context=context,
    )


class _CapturingSandbox:
    def __init__(self, output: str = "ok") -> None:
        self.calls: list[dict] = []
        self._output = output

    def execute_command(self, command: str, env=None, timeout=None) -> str:
        self.calls.append({"command": command, "env": env, "timeout": timeout})
        return self._output


def _run_bash(monkeypatch, runtime, command: str = "echo hi") -> _CapturingSandbox:
    sandbox = _CapturingSandbox()
    monkeypatch.setattr("vassilflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    monkeypatch.setattr("vassilflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
    bash_tool.func(runtime=runtime, description="test", command=command)
    return sandbox


class TestMergeRunContextOverridesChannelUserId:
    def test_channel_user_id_propagates_to_runtime_context_only(self):
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        merge_run_context_overrides(config, {"channel_user_id": "ou_feishu_123"})

        assert config["context"]["channel_user_id"] == "ou_feishu_123"
        assert "channel_user_id" not in config["configurable"]

    def test_existing_runtime_context_value_wins(self):
        from app.gateway.services import build_run_config, merge_run_context_overrides

        config = build_run_config("thread-1", None, None)
        config.setdefault("context", {})["channel_user_id"] = "server-stamped"
        merge_run_context_overrides(config, {"channel_user_id": "client-supplied"})

        assert config["context"]["channel_user_id"] == "server-stamped"


class TestGatewayPrivateContextStripping:
    def test_build_run_config_strips_caller_private_context_keys(self):
        from app.gateway.services import build_run_config

        config = build_run_config(
            "thread-1",
            {
                "context": {
                    "__slash_skill_secret_source": {"path": "/mnt/skills/custom/evil/SKILL.md"},
                    "__active_skill_secrets": {"API_TOKEN": "forged"},
                    "secrets": {"API_TOKEN": "caller-secret"},
                    "model_name": "gpt-test",
                }
            },
            None,
        )

        assert "__slash_skill_secret_source" not in config["context"]
        assert "__active_skill_secrets" not in config["context"]
        assert config["context"]["secrets"] == {"API_TOKEN": "caller-secret"}
        assert config["context"]["model_name"] == "gpt-test"


class TestBashToolChannelIdentityPrefix:
    def test_identity_exported_and_env_stays_none(self, monkeypatch):
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "ou_feishu_123"}))

        assert len(sandbox.calls) == 1
        assert sandbox.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}=ou_feishu_123; echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_no_channel_user_id_leaves_command_unchanged(self, monkeypatch):
        sandbox = _run_bash(monkeypatch, _aio_runtime({"thread_id": "t1"}))

        assert sandbox.calls[0]["command"] == "echo hi"
        assert sandbox.calls[0]["env"] is None

    def test_per_call_identity_follows_current_context(self, monkeypatch):
        first = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-a"}))
        second = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-b"}))

        assert "sender-a" in first.calls[0]["command"]
        assert "sender-b" in second.calls[0]["command"]

    def test_value_is_shell_quoted(self, monkeypatch):
        sandbox = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "x'; rm -rf /tmp/y; '"}))

        assert sandbox.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}='x'\"'\"'; rm -rf /tmp/y; '\"'\"''; echo hi"

    def test_secrets_and_identity_compose(self, monkeypatch):
        runtime = _aio_runtime(
            {
                "channel_user_id": "ou_1",
                "__active_skill_secrets": {"ERP_TOKEN": "secret-value"},
            }
        )
        sandbox = _run_bash(monkeypatch, runtime)

        call = sandbox.calls[0]
        assert call["env"] == {"ERP_TOKEN": "secret-value"}
        assert call["command"].startswith(f"export {CHANNEL_USER_ID_ENV}=ou_1; ")
        assert "secret-value" not in call["command"]

    def test_non_im_run_leaves_command_untouched(self):
        assert _channel_identity_prefix(SimpleNamespace(context={"thread_id": "t1"})) is None
        assert _channel_identity_prefix(SimpleNamespace(context={})) is None
        assert _channel_identity_prefix(SimpleNamespace(context=None)) is None

    def test_unusable_value_emits_unset_not_none(self):
        for bad in ("", 123, "x" * 5000, None):
            assert _channel_identity_prefix(SimpleNamespace(context={"channel_user_id": bad})) == f"unset {CHANNEL_USER_ID_ENV}; "

    def test_group_chat_dropped_id_clears_previous_sender(self, monkeypatch):
        first = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "sender-a"}))
        second = _run_bash(monkeypatch, _aio_runtime({"channel_user_id": "b" * 5000}))

        assert first.calls[0]["command"] == f"export {CHANNEL_USER_ID_ENV}=sender-a; echo hi"
        assert second.calls[0]["command"] == f"unset {CHANNEL_USER_ID_ENV}; echo hi"
        assert second.calls[0]["env"] is None

    def test_windows_local_sandbox_skips_prefix(self, monkeypatch):
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"channel_user_id": "ou_1", "thread_id": "t1"},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("vassilflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("vassilflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("vassilflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("vassilflow.sandbox.tools._is_windows", lambda: True)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert len(sandbox.calls) == 1
        assert "export" not in sandbox.calls[0]["command"]

    def test_posix_local_sandbox_gets_prefix(self, monkeypatch):
        runtime = SimpleNamespace(
            state={"sandbox": {"sandbox_id": "local"}, "thread_data": _THREAD_DATA.copy()},
            context={"channel_user_id": "ou_1", "thread_id": "t1"},
        )
        sandbox = _CapturingSandbox()
        monkeypatch.setattr("vassilflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
        monkeypatch.setattr("vassilflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)
        monkeypatch.setattr("vassilflow.sandbox.tools.is_host_bash_allowed", lambda: True)
        monkeypatch.setattr("vassilflow.sandbox.tools._is_windows", lambda: False)

        bash_tool.func(runtime=runtime, description="test", command="echo hi")

        assert sandbox.calls[0]["command"].startswith(f"export {CHANNEL_USER_ID_ENV}=ou_1; ")
        assert sandbox.calls[0]["command"].endswith("echo hi")
