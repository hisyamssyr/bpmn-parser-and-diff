from __future__ import annotations

from pathlib import Path

from core.bpmn_diff import diff_files
from core.bpmn_parser import parse_bpmn

FIXTURES = Path(__file__).parent / "fixtures"
SIMPLE_ERP = FIXTURES / "simple_erp"

EXPECTED_COUNTS = {
    "l0-enterprise-landscape.bpmn": (1, 0, 0, 12, 18),
    "l1-core-processes.bpmn": (4, 4, 0, 23, 20),
    "l2-access-lifecycle.bpmn": (1, 1, 3, 14, 14),
    "l2-inventory-adjustment.bpmn": (1, 0, 3, 11, 11),
    "l2-order-to-cash.bpmn": (1, 2, 3, 21, 28),
    "l2-procure-to-pay.bpmn": (1, 2, 3, 23, 29),
}

RETYPED_NODES = {
    "AUTH-L1-INVITE",
    "AUTH-L1-RESET",
    "INV-L1-APPROVE",
    "INV-L1-COUNT",
    "INV-L1-POST",
    "O2C-L1-CASH",
    "O2C-L1-DELIVER",
    "O2C-L1-INVOICE",
    "O2C-L1-ORDER",
    "P2P-L1-ORDER",
    "P2P-L1-PAY",
    "P2P-L1-RECEIVE",
    "P2P-L1-REQ",
}

RENAMED_NODES = {
    "AUTH-L1-END",
    "AUTH-L1-START",
    "INV-L1-END",
    "INV-L1-START",
    "O2C-L1-END",
    "O2C-L1-START",
    "P2P-L1-END",
    "P2P-L1-START",
}


def test_parse_six_original_files() -> None:
    files = sorted(SIMPLE_ERP.glob("*.bpmn"))
    assert len(files) == 6

    totals = {"processes": 0, "participants": 0, "lanes": 0, "nodes": 0, "flows": 0}
    for path in files:
        model = parse_bpmn(path)
        counts = (
            len(model["processes"]),
            len(model["participants"]),
            len(model["lanes"]),
            len(model["nodes"]),
            len(model["flows"]),
        )
        assert counts == EXPECTED_COUNTS[path.name]

        for key, value in zip(totals, counts):
            totals[key] += value
        assert model["warnings"] == []

    assert totals == {
        "processes": 9,
        "participants": 9,
        "lanes": 12,
        "nodes": 104,
        "flows": 120,
    }


def test_s00_diff_from_commit_f5a556b() -> None:
    result = diff_files(
        FIXTURES / "s00_old.bpmn",
        FIXTURES / "s00_new.bpmn",
    )

    assert result["summary"]["identical"] is False
    assert result["summary"]["nodes"] == {
        "added": 0,
        "removed": 0,
        "changed": 21,
    }
    for category in ("flows", "lanes", "processes"):
        assert result["summary"][category] == {
            "added": 0,
            "removed": 0,
            "changed": 0,
        }
    assert result["warnings"] == []

    changed = {entry["id"]: entry for entry in result["nodes"]["changed"]}
    assert set(changed) == RETYPED_NODES | RENAMED_NODES

    for node_id in RETYPED_NODES:
        entry = changed[node_id]
        assert entry["kinds"] == ["retyped"]
        assert entry["fields"]["type"] == {
            "old": "subProcess",
            "new": "task",
        }

    for node_id in RENAMED_NODES:
        entry = changed[node_id]
        assert entry["kinds"] == ["renamed"]
        assert "name" in entry["fields"]
