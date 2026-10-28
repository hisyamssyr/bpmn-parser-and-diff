from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from core.bpmn_diff import (
    diff_dirs,
    diff_files,
    diff_models,
    get_context,
    get_element,
)
from core.bpmn_parser import BPMN_NAMESPACE, BpmnParseError, parse_bpmn
from tests.helpers import make_flow, make_lane, make_model, make_node

FIXTURES = Path(__file__).parent / "fixtures"


def test_identical_ignores_di_order_and_whitespace() -> None:
    old = parse_bpmn(FIXTURES / "identical_old.bpmn")
    new = parse_bpmn(FIXTURES / "identical_new.bpmn")
    result = diff_models(old, new)

    assert result["summary"]["identical"] is True
    for category in ("nodes", "flows", "lanes", "processes"):
        assert result["summary"][category] == {
            "added": 0,
            "removed": 0,
            "changed": 0,
        }
    assert result["warnings"] == []
    assert result["summary"]["possible_renames"] == []


def test_retyped_node_with_context() -> None:
    result = diff_files(
        FIXTURES / "basic_old.bpmn",
        FIXTURES / "basic_new.bpmn",
    )

    assert result["summary"]["identical"] is False
    assert result["summary"]["nodes"] == {
        "added": 0,
        "removed": 0,
        "changed": 1,
    }
    assert result["nodes"]["changed"] == [
        {
            "id": "S00",
            "kinds": ["retyped"],
            "fields": {"type": {"old": "subProcess", "new": "task"}},
            "context": {
                "incoming": [
                    {
                        "flow": "F1",
                        "node": "START",
                        "name": "Mulai",
                        "type": "startEvent",
                    }
                ],
                "outgoing": [
                    {
                        "flow": "F2",
                        "node": "END",
                        "name": "Selesai",
                        "type": "endEvent",
                    }
                ],
            },
        }
    ]
    assert result["flows"]["changed"] == []
    assert result["lanes"]["changed"] == []
    assert result["processes"]["changed"] == []


def test_lane_and_process_changes() -> None:
    result = diff_files(
        FIXTURES / "lanes_old.bpmn",
        FIXTURES / "lanes_new.bpmn",
    )

    assert result["summary"]["lanes"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
    }
    assert [lane["id"] for lane in result["lanes"]["added"]] == ["L3"]
    assert [lane["id"] for lane in result["lanes"]["removed"]] == ["L2"]
    assert result["lanes"]["changed"] == [
        {
            "id": "L1",
            "kinds": ["renamed"],
            "fields": {"name": {"old": "Divisi", "new": "Divisi Baru"}},
        }
    ]

    assert result["summary"]["nodes"]["changed"] == 1
    assert result["nodes"]["changed"] == [
        {
            "id": "T2",
            "kinds": ["lane_moved"],
            "fields": {"lane_id": {"old": "L2", "new": "L3"}},
            "context": {"incoming": [], "outgoing": []},
        }
    ]

    assert result["processes"]["changed"] == [
        {
            "id": "PROC",
            "kinds": ["renamed"],
            "fields": {"name": {"old": "Proses Lama", "new": "Proses Baru"}},
        }
    ]


def test_feature_field_labels() -> None:
    result = diff_files(
        FIXTURES / "features_old.bpmn",
        FIXTURES / "features_new.bpmn",
    )

    assert result["summary"]["nodes"]["changed"] == 5
    assert result["summary"]["flows"]["changed"] == 4
    assert result["warnings"] == []

    changed_nodes = {entry["id"]: entry for entry in result["nodes"]["changed"]}
    assert changed_nodes["TASK"]["kinds"] == [
        "documentation_changed",
        "loop_changed",
    ]
    assert changed_nodes["TASK"]["fields"]["loop"] == {
        "old": "",
        "new": "standard",
    }
    assert changed_nodes["GW"]["kinds"] == [
        "default_flow_changed",
        "gateway_direction_changed",
    ]
    assert changed_nodes["EVT"]["kinds"] == ["event_definition_changed"]
    assert changed_nodes["CALL"]["kinds"] == ["called_element_changed"]
    assert changed_nodes["BND"]["kinds"] == [
        "attached_to_changed",
        "cancel_activity_changed",
    ]

    changed_flows = {entry["id"]: entry for entry in result["flows"]["changed"]}
    assert changed_flows["F1"]["kinds"] == ["renamed"]
    assert changed_flows["F2"]["kinds"] == ["condition_changed"]
    assert changed_flows["F3"]["kinds"] == [
        "condition_changed",
        "rewired_source",
    ]
    assert changed_flows["F4"]["kinds"] == ["renamed", "rewired_target"]


def test_context_and_endpoints() -> None:
    result = diff_files(
        FIXTURES / "context_old.bpmn",
        FIXTURES / "context_new.bpmn",
    )

    assert result["summary"]["nodes"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
    }
    assert result["summary"]["flows"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
    }

    added_node = result["nodes"]["added"][0]
    assert added_node["node"]["id"] == "D"
    assert added_node["context"]["incoming"] == [
        {
            "flow": "F1",
            "node": "A",
            "name": "Awal",
            "type": "startEvent",
        },
        {
            "flow": "F3",
            "node": "B",
            "name": "Tengah Baru",
            "type": "task",
        },
    ]
    assert added_node["context"]["outgoing"] == []

    removed_node = result["nodes"]["removed"][0]
    assert removed_node["node"]["id"] == "C"
    assert removed_node["context"] == {
        "incoming": [
            {
                "flow": "F2",
                "node": "B",
                "name": "Tengah",
                "type": "task",
            }
        ],
        "outgoing": [],
    }

    changed_node = result["nodes"]["changed"][0]
    assert changed_node["id"] == "B"
    assert changed_node["kinds"] == ["renamed"]
    assert changed_node["context"]["incoming"] == []
    assert changed_node["context"]["outgoing"][0]["flow"] == "F3"

    added_flow = result["flows"]["added"][0]
    assert added_flow["flow"]["id"] == "F3"
    assert added_flow["endpoints"] == {
        "source": {"id": "B", "type": "task", "name": "Tengah Baru"},
        "target": {"id": "D", "type": "endEvent", "name": "Akhir Baru"},
    }

    removed_flow = result["flows"]["removed"][0]
    assert removed_flow["flow"]["id"] == "F2"
    assert removed_flow["endpoints"] == {
        "source": {"id": "B", "type": "task", "name": "Tengah"},
        "target": {"id": "C", "type": "endEvent", "name": "Akhir"},
    }

    changed_flow = result["flows"]["changed"][0]
    assert changed_flow["id"] == "F1"
    assert changed_flow["kinds"] == ["rewired_target"]
    assert changed_flow["fields"] == {"target": {"old": "B", "new": "D"}}
    assert changed_flow["endpoints"] == {
        "source": {"id": "A", "type": "startEvent", "name": "Awal"},
        "target": {"id": "D", "type": "endEvent", "name": "Akhir Baru"},
    }
    assert changed_flow["endpoints_old"] == {
        "source": {"id": "A", "type": "startEvent", "name": "Awal"},
        "target": {"id": "B", "type": "task", "name": "Tengah"},
    }


NODE_FIELD_CASES = [
    ("type", "task", "userTask", "retyped"),
    ("name", "Nama Lama", "Nama Baru", "renamed"),
    ("lane_id", "L1", "L2", "lane_moved"),
    ("parent", "P", "SUB", "reparented"),
    (
        "documentation",
        "Dokumen lama",
        "Dokumen baru",
        "documentation_changed",
    ),
    ("default_flow", "F1", "F2", "default_flow_changed"),
    (
        "gateway_direction",
        "Converging",
        "Diverging",
        "gateway_direction_changed",
    ),
    ("event_definition", "", "timer", "event_definition_changed"),
    ("loop", "", "standard", "loop_changed"),
    ("called_element", "PROC-A", "PROC-B", "called_element_changed"),
    ("attached_to", "A", "B", "attached_to_changed"),
    ("cancel_activity", "true", "false", "cancel_activity_changed"),
]


@pytest.mark.parametrize(("field", "old_value", "new_value", "kind"), NODE_FIELD_CASES)
def test_node_field_kinds(
    field: str, old_value: str, new_value: str, kind: str
) -> None:
    old = make_model(nodes={"N": make_node("N", **{field: old_value})})
    new = make_model(nodes={"N": make_node("N", **{field: new_value})})

    entry = diff_models(old, new)["nodes"]["changed"][0]
    assert entry["kinds"] == [kind]
    assert entry["fields"] == {field: {"old": old_value, "new": new_value}}


FLOW_FIELD_CASES = [
    ("type", "sequence", "message", "retyped"),
    ("source", "A", "C", "rewired_source"),
    ("target", "B", "C", "rewired_target"),
    ("name", "Lama", "Baru", "renamed"),
    ("condition", "x > 0", "x < 0", "condition_changed"),
    ("parent", "P", "SUB", "reparented"),
]


@pytest.mark.parametrize(("field", "old_value", "new_value", "kind"), FLOW_FIELD_CASES)
def test_flow_field_kinds(
    field: str, old_value: str, new_value: str, kind: str
) -> None:
    old_flow = make_flow("F", "A", "B")
    new_flow = make_flow("F", "A", "B")
    old_flow[field] = old_value
    new_flow[field] = new_value
    old = make_model(flows={"F": old_flow})
    new = make_model(flows={"F": new_flow})

    entry = diff_models(old, new)["flows"]["changed"][0]
    assert entry["kinds"] == [kind]
    assert entry["fields"] == {field: {"old": old_value, "new": new_value}}


def test_lane_and_process_field_kinds() -> None:
    old_lane = make_lane("L1", "Lama", parent_lane="")
    new_lane = make_lane("L1", "Baru", parent_lane="L0")
    old = make_model(lanes={"L1": old_lane})
    new = make_model(lanes={"L1": new_lane})

    entry = diff_models(old, new)["lanes"]["changed"][0]
    assert entry["kinds"] == ["renamed", "reparented"]
    assert entry["fields"]["name"] == {"old": "Lama", "new": "Baru"}
    assert entry["fields"]["parent_lane"] == {"old": "", "new": "L0"}

    old_process = make_model(processes=[{"id": "P", "name": "Lama"}])
    new_process = make_model(processes=[{"id": "P", "name": "Baru"}])
    entry = diff_models(old_process, new_process)["processes"]["changed"][0]
    assert entry == {
        "id": "P",
        "kinds": ["renamed"],
        "fields": {"name": {"old": "Lama", "new": "Baru"}},
    }

    old_participant = make_model(
        processes=[],
        participants=[{"id": "PART", "name": "Lama", "process_ref": "P"}],
    )
    new_participant = make_model(
        processes=[],
        participants=[{"id": "PART", "name": "Baru", "process_ref": "P"}],
    )
    entry = diff_models(old_participant, new_participant)["processes"]["changed"][0]
    assert entry["id"] == "PART"
    assert entry["kinds"] == ["renamed"]


def test_process_added_and_removed() -> None:
    result = diff_models(
        make_model(nodes={}, processes=[{"id": "OLD", "name": "Lama"}]),
        make_model(nodes={}, processes=[{"id": "NEW", "name": "Baru"}]),
    )

    assert result["processes"]["added"] == [{"id": "NEW", "name": "Baru"}]
    assert result["processes"]["removed"] == [{"id": "OLD", "name": "Lama"}]
    assert result["summary"]["processes"] == {
        "added": 1,
        "removed": 1,
        "changed": 0,
    }


def test_multiple_kinds_are_sorted() -> None:
    old = make_model(nodes={"N": make_node("N", type="task", lane_id="L1", name="A")})
    new = make_model(
        nodes={"N": make_node("N", type="userTask", lane_id="L2", name="B")}
    )
    entry = diff_models(old, new)["nodes"]["changed"][0]
    assert entry["kinds"] == ["lane_moved", "renamed", "retyped"]

    old_flow = make_model(flows={"F": make_flow("F", "A", "B")})
    new_flow = make_model(flows={"F": make_flow("F", "C", "D")})
    entry = diff_models(old_flow, new_flow)["flows"]["changed"][0]
    assert entry["kinds"] == ["rewired_source", "rewired_target"]


def test_lane_rename_does_not_change_nodes() -> None:
    old = make_model(
        lanes={"L1": make_lane("L1", "Lama")},
        nodes={"N": make_node("N", lane_id="L1", lane="Lama")},
    )
    new = make_model(
        lanes={"L1": make_lane("L1", "Baru")},
        nodes={"N": make_node("N", lane_id="L1", lane="Baru")},
    )
    result = diff_models(old, new)

    assert result["nodes"]["changed"] == []
    assert result["lanes"]["changed"][0]["kinds"] == ["renamed"]


def test_removed_all_nodes_sorted() -> None:
    result = diff_models(
        make_model(nodes={"B": make_node("B"), "A": make_node("A")}),
        make_model(nodes={}),
    )

    assert [entry["node"]["id"] for entry in result["nodes"]["removed"]] == [
        "A",
        "B",
    ]
    assert result["summary"]["identical"] is False
    assert result["warnings"] == []


def test_no_overlapping_ids_warning_and_strict() -> None:
    old = make_model(nodes={"A": make_node("A", name="Sama")})
    new = make_model(nodes={"B": make_node("B", name="Sama")})
    result = diff_models(old, new)

    assert result["warnings"] == [
        {
            "side": "diff",
            "code": "NO_OVERLAPPING_IDS",
            "message": "The two models have no node IDs in common",
            "element_id": "",
        }
    ]
    with pytest.raises(BpmnParseError, match="NO_OVERLAPPING_IDS"):
        diff_models(old, new, strict=True)

    empty = diff_models(make_model(nodes={}), make_model(nodes={}))
    assert empty["warnings"] == []
    assert empty["summary"]["identical"] is True


def test_model_warnings_carry_side_and_strict() -> None:
    old = make_model(
        nodes={},
        warnings=[{"code": "MISSING_ID", "message": "lama", "element_id": "A"}],
    )
    new = make_model(
        nodes={},
        warnings=[{"code": "DANGLING_REF", "message": "baru", "element_id": "B"}],
    )
    result = diff_models(old, new)

    assert [(warning["side"], warning["code"]) for warning in result["warnings"]] == [
        ("old", "MISSING_ID"),
        ("new", "DANGLING_REF"),
    ]
    with pytest.raises(BpmnParseError, match="strict"):
        diff_models(old, new, strict=True)


def test_possible_renames() -> None:
    old = make_model(
        nodes={
            "A-1": make_node("A-1", name="Sama", lane_id="L1"),
            "B-1": make_node("B-1", name="Beda", lane_id="L1"),
        }
    )
    new = make_model(
        nodes={
            "A-2": make_node("A-2", name="Sama", lane_id="L1"),
            "B-2": make_node("B-2", name="Lain", lane_id="L1"),
        }
    )
    result = diff_models(old, new)

    assert result["summary"]["possible_renames"] == [
        {
            "removed": "A-1",
            "added": "A-2",
            "basis": ["type", "name", "lane"],
        }
    ]
    assert [entry["node"]["id"] for entry in result["nodes"]["removed"]] == [
        "A-1",
        "B-1",
    ]
    assert [entry["node"]["id"] for entry in result["nodes"]["added"]] == [
        "A-2",
        "B-2",
    ]


def test_case_sensitivity() -> None:
    result = diff_models(
        make_model(nodes={"T": make_node("T", name="Tugas")}),
        make_model(nodes={"T": make_node("T", name="tugas")}),
    )
    assert result["nodes"]["changed"][0]["kinds"] == ["renamed"]

    result = diff_models(
        make_model(nodes={"T": make_node("T", name="Tugas")}),
        make_model(nodes={"t": make_node("t", name="Tugas")}),
    )
    assert [entry["node"]["id"] for entry in result["nodes"]["removed"]] == ["T"]
    assert [entry["node"]["id"] for entry in result["nodes"]["added"]] == ["t"]
    assert result["warnings"][0]["code"] == "NO_OVERLAPPING_IDS"


def test_get_element_and_get_context() -> None:
    model = make_model(
        nodes={
            "A": make_node("A", name="Awal", type="startEvent", lane_id="L"),
            "B": make_node("B", name="Tengah", lane_id="L"),
        },
        flows={
            "F2": make_flow("F2", "B", "A"),
            "F1": make_flow("F1", "A", "B"),
        },
        lanes={"L": make_lane("L", "Lane")},
        processes=[{"id": "P", "name": "Proses"}],
        participants=[{"id": "PART", "name": "Pool", "process_ref": "P"}],
    )

    assert get_element(model, "A")["name"] == "Awal"
    assert get_element(model, "F1")["target"] == "B"
    assert get_element(model, "L")["name"] == "Lane"
    assert get_element(model, "P")["name"] == "Proses"
    assert get_element(model, "PART")["name"] == "Pool"
    assert get_element(model, "TIDAK_ADA") is None

    context = get_context(model, "A")
    assert context["incoming"] == [
        {"flow": "F2", "node": "B", "name": "Tengah", "type": "task"}
    ]
    assert context["outgoing"] == [
        {"flow": "F1", "node": "B", "name": "Tengah", "type": "task"}
    ]
    assert get_context(model, "TIDAK_ADA") == {
        "incoming": [],
        "outgoing": [],
    }


def test_flow_endpoints_with_missing_node() -> None:
    result = diff_models(
        make_model(nodes={}),
        make_model(nodes={}, flows={"F": make_flow("F", "X", "Y")}),
    )
    assert result["flows"]["added"][0]["endpoints"] == {
        "source": {"id": "X", "type": "", "name": ""},
        "target": {"id": "Y", "type": "", "name": ""},
    }


def test_json_shape_and_determinism() -> None:
    old = parse_bpmn(FIXTURES / "s00_old.bpmn")
    new = parse_bpmn(FIXTURES / "s00_new.bpmn")
    result = diff_models(old, new)

    assert list(result) == [
        "schema_version",
        "old_file",
        "new_file",
        "summary",
        "nodes",
        "flows",
        "lanes",
        "processes",
        "warnings",
    ]
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result
    assert diff_models(old, new) == result

    old_a = make_model(
        nodes={"B": make_node("B"), "A": make_node("A")},
        flows={
            "F2": make_flow("F2", "B", "A"),
            "F1": make_flow("F1", "A", "B"),
        },
    )
    old_b = make_model(
        nodes={"A": make_node("A"), "B": make_node("B")},
        flows={
            "F1": make_flow("F1", "A", "B"),
            "F2": make_flow("F2", "B", "A"),
        },
    )
    new_model = make_model(
        nodes={"A": make_node("A", name="Baru"), "B": make_node("B")},
        flows={
            "F1": make_flow("F1", "A", "B"),
            "F2": make_flow("F2", "B", "A"),
        },
    )
    assert diff_models(old_a, new_model) == diff_models(old_b, new_model)


def test_diff_files_and_missing_input() -> None:
    result = diff_files(
        str(FIXTURES / "s00_old.bpmn"),
        str(FIXTURES / "s00_new.bpmn"),
    )
    assert result["old_file"] == str(FIXTURES / "s00_old.bpmn")
    assert result["new_file"] == str(FIXTURES / "s00_new.bpmn")

    with pytest.raises(BpmnParseError):
        diff_files(FIXTURES / "tidak-ada.bpmn", FIXTURES / "s00_new.bpmn")


def test_performance_5000_nodes(tmp_path: Path) -> None:
    tasks = "".join(
        f'<task id="T{index:04d}" name="Tugas {index}"/>' for index in range(5000)
    )
    flows = "".join(
        f'<sequenceFlow id="F{index:04d}" '
        f'sourceRef="T{index:04d}" targetRef="T{index + 1:04d}"/>'
        for index in range(4999)
    )
    xml = (
        f'<definitions xmlns="{BPMN_NAMESPACE}" id="D">'
        f'<process id="P" name="Proses">{tasks}{flows}</process>'
        "</definitions>"
    )
    path = tmp_path / "besar.bpmn"
    path.write_text(xml, encoding="utf-8")

    started = time.perf_counter()
    old = parse_bpmn(path)
    new = parse_bpmn(path)
    result = diff_models(old, new)
    elapsed = time.perf_counter() - started

    assert len(old["nodes"]) == 5000
    assert len(old["flows"]) == 4999
    assert result["summary"]["identical"] is True
    assert elapsed < 5.0


def test_diff_dirs(tmp_path: Path) -> None:
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()

    shutil.copyfile(FIXTURES / "s00_old.bpmn", old_dir / "s00.bpmn")
    shutil.copyfile(FIXTURES / "s00_new.bpmn", new_dir / "s00.bpmn")
    shutil.copyfile(FIXTURES / "lanes_old.bpmn", old_dir / "lanes.bpmn")
    shutil.copyfile(FIXTURES / "lanes_new.bpmn", new_dir / "lanes.bpmn")
    shutil.copyfile(FIXTURES / "identical_old.bpmn", old_dir / "same.bpmn")
    shutil.copyfile(FIXTURES / "identical_new.bpmn", new_dir / "same.bpmn")
    shutil.copyfile(FIXTURES / "identical_old.bpmn", old_dir / "only_old.bpmn")
    shutil.copyfile(FIXTURES / "identical_new.bpmn", new_dir / "only_new.bpmn")

    result = diff_dirs(old_dir, new_dir)

    assert result["schema_version"] == "1.0"
    assert result["files"]["added"] == ["only_new.bpmn"]
    assert result["files"]["removed"] == ["only_old.bpmn"]
    assert [Path(item["old_file"]).name for item in result["files"]["changed"]] == [
        "lanes.bpmn",
        "s00.bpmn",
    ]
    assert all(
        item["summary"]["identical"] is False for item in result["files"]["changed"]
    )

    with pytest.raises(BpmnParseError):
        diff_dirs(tmp_path / "tidak-ada", new_dir)
