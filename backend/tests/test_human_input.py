from vassilflow.agents.human_input import read_human_input_response


def test_read_human_input_text_response():
    payload = {
        "human_input_response": {
            "version": 1,
            "kind": "human_input_response",
            "source": "ask_clarification",
            "request_id": "clarification:call-abc",
            "response_kind": "text",
            "value": "harness agent",
        }
    }

    assert read_human_input_response(payload) == {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "clarification:call-abc",
        "response_kind": "text",
        "value": "harness agent",
    }


def test_read_human_input_option_response():
    payload = {
        "human_input_response": {
            "version": 1,
            "kind": "human_input_response",
            "source": "ask_clarification",
            "request_id": "clarification:call-abc",
            "response_kind": "option",
            "option_id": "option-2",
            "value": "staging",
        }
    }

    assert read_human_input_response(payload) == {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": "clarification:call-abc",
        "response_kind": "option",
        "option_id": "option-2",
        "value": "staging",
    }


def test_read_human_input_response_rejects_empty_value():
    payload = {
        "human_input_response": {
            "version": 1,
            "kind": "human_input_response",
            "source": "ask_clarification",
            "request_id": "clarification:call-abc",
            "response_kind": "text",
            "value": "",
        }
    }

    assert read_human_input_response(payload) is None


def test_read_human_input_response_rejects_option_without_option_id():
    payload = {
        "human_input_response": {
            "version": 1,
            "kind": "human_input_response",
            "source": "ask_clarification",
            "request_id": "clarification:call-abc",
            "response_kind": "option",
            "value": "staging",
        }
    }

    assert read_human_input_response(payload) is None
