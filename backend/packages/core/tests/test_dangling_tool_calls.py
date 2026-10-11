"""Recovery preserves causal tool order without mutating checkpoint messages."""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import PrivateAttr

from vassilflow_core.agents import create_agent
from vassilflow_core.middleware import DanglingToolCallMiddleware


class CaptureModel(FakeMessagesListChatModel):
    _seen: list = PrivateAttr(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_real_graph_recovers_interrupted_tool_call_before_model():
    model = CaptureModel(responses=[AIMessage(content="Recovered")])
    graph = create_agent(model)
    interrupted = AIMessage(
        content="", tool_calls=[{"name": "lookup", "args": {}, "id": "interrupted-call", "type": "tool_call"}]
    )
    messages = [interrupted, HumanMessage(content="Continue")]
    result = graph.invoke({"messages": messages})
    received = model._seen[0]
    assert isinstance(received[0], AIMessage)
    assert isinstance(received[1], ToolMessage)
    assert received[1].tool_call_id == "interrupted-call"
    assert received[1].status == "error"
    assert isinstance(received[2], HumanMessage)
    assert result["messages"][-1].content == "Recovered"
    assert not any(isinstance(message, ToolMessage) for message in result["messages"])
    assert len(messages) == 2


def test_existing_results_are_reordered_without_replacing_or_duplicating_them():
    middleware = DanglingToolCallMiddleware()
    assistant = AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "call-a", "type": "tool_call"}])
    human = HumanMessage(content="Continue")
    result = ToolMessage(content="Found it", tool_call_id="call-a")
    original = [assistant, human, result]
    patched = middleware._build_patched_messages(original)
    assert patched == [assistant, result, human]
    assert patched[1] is result
    assert original == [assistant, human, result]
    assert middleware._build_patched_messages(patched) is None


def test_raw_provider_calls_get_a_matching_recovery_message():
    assistant = AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [
                {"id": "raw-call", "type": "function", "function": {"name": "lookup", "arguments": "{invalid"}}
            ]
        },
    )
    patched = DanglingToolCallMiddleware()._build_patched_messages([assistant])
    assert patched is not None
    assert patched[1].tool_call_id == "raw-call"
    assert patched[1].status == "error"
