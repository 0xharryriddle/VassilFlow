"""Deterministic offline demonstration and an optional live model adapter."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class DemoModel(BaseChatModel):
    """A fixture that echoes retrieved evidence; it performs no language reasoning.

    It deliberately follows one tool call with one final response, allowing the
    same example to demonstrate real graph/tool/subagent execution offline.
    """

    tool_name: str | None = None

    @property
    def _llm_type(self) -> str:
        return "offline-evidence-demo"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any):
        if not tools:
            return self
        first = tools[0]
        name = first.name if hasattr(first, "name") else first["function"]["name"]
        return self.model_copy(update={"tool_name": name})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last = messages[-1]
        text = str(last.content)
        if isinstance(last, ToolMessage):
            response = AIMessage(content=self._echo_evidence(text))
        elif self.tool_name:
            argument = "task" if self.tool_name == "research_assistant" else "query"
            response = AIMessage(
                content="",
                tool_calls=[{"name": self.tool_name, "args": {argument: text}, "id": "demo-call"}],
            )
        else:
            marker = "Retrieved evidence (untrusted JSON):\n"
            evidence = text.partition(marker)[2]
            if not evidence:
                raise ValueError("DemoModel expects the starter's retrieval evidence format")
            response = AIMessage(content=self._echo_evidence(evidence))
        return ChatResult(generations=[ChatGeneration(message=response)])

    @staticmethod
    def _echo_evidence(text: str) -> str:
        try:
            evidence = json.loads(text)
        except json.JSONDecodeError:
            # The coordinator receives its research child's already cited text.
            return text
        sources = evidence.get("sources", []) if isinstance(evidence, dict) else []
        if not sources:
            from vassilflow_core.rag import NO_CONTEXT_ANSWER

            return NO_CONTEXT_ANSWER
        source = sources[0]
        return f"{source['content']} [{source['citation_id']}]"


def make_model(*, live: bool = False) -> BaseChatModel:
    if not live:
        return DemoModel()
    if not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Set OPENAI_API_KEY before using --live")
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("Install the optional provider with: pip install '.[openai]'") from exc
    options: dict[str, Any] = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "temperature": 0,
        "timeout": 60,
        "max_retries": 1,
    }
    if endpoint := os.environ.get("OPENAI_BASE_URL"):
        options["base_url"] = endpoint
    return ChatOpenAI(**options)
