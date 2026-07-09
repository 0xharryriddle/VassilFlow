from types import SimpleNamespace

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from vassilflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from vassilflow.agents.middlewares.skill_context import extract_skills, render_skill_context


def _skill_read_call(tool_id: str, path: str = "/mnt/skills/public/data-analysis/SKILL.md") -> dict:
    return {"name": "read_file", "id": tool_id, "args": {"path": path}}


def test_extract_skills_uses_stamped_metadata():
    messages = [
        AIMessage(content="", tool_calls=[_skill_read_call("tc-1")]),
        ToolMessage(
            content="---\nname: data-analysis\ndescription: Analyze data\n---\n# Skill\n",
            tool_call_id="tc-1",
            additional_kwargs={
                "skill_context_entry": {
                    "path": "/mnt/skills/public/data-analysis/SKILL.md",
                    "description": "Analyze data",
                }
            },
        ),
    ]

    entries = extract_skills(messages, skills_root="/mnt/skills", read_tool_names={"read_file"})

    assert entries == [
        {
            "name": "data-analysis",
            "path": "/mnt/skills/public/data-analysis/SKILL.md",
            "description": "Analyze data",
            "loaded_at": 1,
        }
    ]


def test_render_skill_context_contains_reference_not_body():
    rendered = render_skill_context(
        [
            {
                "name": "data-analysis",
                "path": "/mnt/skills/public/data-analysis/SKILL.md",
                "description": "Analyze data",
                "loaded_at": 1,
            }
        ]
    )

    assert "data-analysis: Analyze data -> /mnt/skills/public/data-analysis/SKILL.md" in rendered
    assert "Skill content" not in rendered


def test_durable_context_middleware_captures_loaded_skill():
    middleware = DurableContextMiddleware(skills_container_path="/mnt/skills", skill_file_read_tool_names={"read_file"})
    state = {
        "messages": [
            AIMessage(content="", tool_calls=[_skill_read_call("tc-1")]),
            ToolMessage(
                content="---\nname: data-analysis\ndescription: Analyze data\n---\n# Skill\n",
                tool_call_id="tc-1",
                additional_kwargs={
                    "skill_context_entry": {
                        "path": "/mnt/skills/public/data-analysis/SKILL.md",
                        "description": "Analyze data",
                    }
                },
            ),
        ]
    }

    update = middleware.before_model(state, SimpleNamespace())

    assert update == {
        "skill_context": [
            {
                "name": "data-analysis",
                "path": "/mnt/skills/public/data-analysis/SKILL.md",
                "description": "Analyze data",
                "loaded_at": 1,
            }
        ]
    }


def test_durable_context_middleware_injects_hidden_skill_context():
    middleware = DurableContextMiddleware()
    request = ModelRequest(
        model=object(),
        messages=[SystemMessage(content="system"), HumanMessage(content="continue")],
        state={
            "messages": [],
            "skill_context": [
                {
                    "name": "data-analysis",
                    "path": "/mnt/skills/public/data-analysis/SKILL.md",
                    "description": "Analyze data",
                    "loaded_at": 1,
                }
            ],
        },
        runtime=SimpleNamespace(),
    )
    captured = {}

    def handler(model_request: ModelRequest):
        captured["messages"] = model_request.messages
        return AIMessage(content="ok")

    middleware.wrap_model_call(request, handler)

    assert isinstance(captured["messages"][0], SystemMessage)
    assert isinstance(captured["messages"][1], SystemMessage)
    assert isinstance(captured["messages"][2], HumanMessage)
    assert captured["messages"][2].additional_kwargs["hide_from_ui"] is True
    assert "data-analysis" in captured["messages"][2].content
