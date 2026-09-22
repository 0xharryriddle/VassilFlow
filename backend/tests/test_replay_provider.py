from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_to_dict
from replay_provider import ReplayChatModel, caller_identity, hash_messages, hash_replay_input


def _write_fixture(path: Path, turns: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "scenario": "unit",
                "mode": "unit",
                "model": "replay",
                "prompt": "unit",
                "context": {},
                "turns": turns,
            }
        ),
        encoding="utf-8",
    )


def test_replay_key_includes_caller_identity(tmp_path: Path):
    messages = [HumanMessage(content="same conversation")]
    lead_output = AIMessage(content="lead")
    suggest_output = AIMessage(content="suggest")
    fixture_path = tmp_path / "fixture.json"

    _write_fixture(
        fixture_path,
        [
            {
                "caller": "lead_agent",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="lead_agent"),
                "output": messages_to_dict([lead_output])[0],
            },
            {
                "caller": "suggest_agent",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="suggest_agent"),
                "output": messages_to_dict([suggest_output])[0],
            },
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))

    assert model.invoke(messages, config={"run_name": "suggest_agent"}).content == "suggest"
    assert model.invoke(messages, config={"run_name": "lead_agent"}).content == "lead"


def test_replay_supports_legacy_conversation_only_fixture(tmp_path: Path):
    messages = [HumanMessage(content="legacy conversation")]
    fixture_path = tmp_path / "legacy.json"

    _write_fixture(
        fixture_path,
        [
            {
                "input_hash": hash_messages(messages),
                "output": messages_to_dict([AIMessage(content="legacy")])[0],
            }
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))

    assert model.invoke(messages, config={"run_name": "suggest_agent"}).content == "legacy"


def test_title_run_name_uses_middleware_caller_namespace(tmp_path: Path):
    messages = [HumanMessage(content="title prompt")]
    fixture_path = tmp_path / "fixture.json"

    _write_fixture(
        fixture_path,
        [
            {
                "caller": "middleware:title",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="middleware:title"),
                "output": messages_to_dict([AIMessage(content="generated title")])[0],
            }
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))

    assert caller_identity(name="title_agent") == "middleware:title"
    assert model.invoke(messages, config={"run_name": "title_agent"}).content == "generated title"


def test_replay_uses_single_pending_capture_when_run_manager_is_missing(tmp_path: Path):
    messages = [HumanMessage(content="title prompt")]
    fixture_path = tmp_path / "fixture.json"

    _write_fixture(
        fixture_path,
        [
            {
                "caller": "middleware:title",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="middleware:title"),
                "output": messages_to_dict([AIMessage(content="generated title")])[0],
            }
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))
    model._run_callers["captured-run"] = caller_identity(name="title_agent", tags=["middleware:title"])

    assert model._match(messages, run_manager=None).content == "generated title"


def test_hash_normalizes_volatile_sample_ids_and_renderer_fingerprint() -> None:
    def tool_result(project_id: str, revision_id: str, fingerprint: str) -> list:
        return [
            HumanMessage(content="create sample data"),
            ToolMessage(
                name="sample_generate",
                tool_call_id="call-generate",
                content=json.dumps(
                    {
                        "project_id": project_id,
                        "revision_id": revision_id,
                        "pipeline_fingerprint": fingerprint,
                    }
                ),
            ),
        ]

    first = tool_result(
        "01234567-89ab-cdef-0123-456789abcdef",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "1" * 64,
    )
    second = tool_result(
        "fedcba98-7654-3210-fedc-ba9876543210",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "2" * 64,
    )

    assert hash_messages(first) == hash_messages(second)


def test_replay_binds_tool_arguments_from_current_tool_result(tmp_path: Path) -> None:
    messages = [
        HumanMessage(content="create sample data"),
        ToolMessage(
            name="sample_generate",
            tool_call_id="call-generate",
            content=json.dumps(
                {
                    "project_id": "fedcba98-7654-3210-fedc-ba9876543210",
                    "revision_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                }
            ),
        ),
    ]
    output = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "sample_render",
                "args": {
                    "path": "/mnt/user-data/outputs/check.txt",
                    "output_dir": "/mnt/user-data/outputs/check-render",
                    "project_id": "<replay-binding>",
                    "revision_id": "<replay-binding>",
                },
                "id": "call-render",
                "type": "tool_call",
            }
        ],
    )
    fixture_path = tmp_path / "sample.json"
    _write_fixture(
        fixture_path,
        [
            {
                "caller": "lead_agent",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="lead_agent"),
                "output": messages_to_dict([output])[0],
                "bindings": [
                    {
                        "tool_call_index": 0,
                        "argument": "project_id",
                        "source_tool": "sample_generate",
                        "source_field": "project_id",
                    },
                    {
                        "tool_call_index": 0,
                        "argument": "revision_id",
                        "source_tool": "sample_generate",
                        "source_field": "revision_id",
                    },
                ],
            }
        ],
    )

    replayed = ReplayChatModel(fixture=str(fixture_path)).invoke(
        messages,
        config={"run_name": "lead_agent"},
    )

    assert replayed.tool_calls[0]["args"]["project_id"] == "fedcba98-7654-3210-fedc-ba9876543210"
    assert replayed.tool_calls[0]["args"]["revision_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
