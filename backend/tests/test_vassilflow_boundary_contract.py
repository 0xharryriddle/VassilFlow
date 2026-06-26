import json
from pathlib import Path


CONTRACT_PATH = Path(__file__).parents[2] / "contracts" / "vassilflow_boundary_contract.json"


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_vassilflow_boundary_contract_is_versioned_json():
    contract = _load_contract()

    assert contract["version"] == 1
    assert "description" in contract
    assert "entities" in contract


def test_vassilflow_boundary_contract_declares_core_entities():
    contract = _load_contract()

    assert set(contract["entities"]) >= {
        "Session",
        "Run",
        "TraceStep",
        "ToolSpec",
        "PolicyDecision",
        "ApprovalRequest",
        "CompletionEvidence",
    }


def test_vassilflow_boundary_contract_declares_policy_decisions():
    contract = _load_contract()

    assert contract["status_values"]["policy_decision"] == [
        "allow",
        "deny",
        "ask",
        "redact",
        "sanitize",
        "escalate",
    ]


def test_vassilflow_boundary_contract_has_completion_events():
    contract = _load_contract()

    assert {"verification.completed", "run.completed", "run.failed"} <= set(contract["event_types"])
