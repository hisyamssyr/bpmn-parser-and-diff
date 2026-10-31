from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from ._cli import display_path, force_utf8
from .bpmn_parser import BpmnParseError, parse_bpmn
from .constants import (
    KIND_ATTACHED_TO_CHANGED,
    KIND_CALLED_ELEMENT_CHANGED,
    KIND_CANCEL_ACTIVITY_CHANGED,
    KIND_CONDITION_CHANGED,
    KIND_DEFAULT_FLOW_CHANGED,
    KIND_DOCUMENTATION_CHANGED,
    KIND_EVENT_DEFINITION_CHANGED,
    KIND_EVENT_DETAIL_CHANGED,
    KIND_GATEWAY_DIRECTION_CHANGED,
    KIND_LANE_MOVED,
    KIND_LOOP_CHANGED,
    KIND_LOOP_DETAIL_CHANGED,
    KIND_RENAMED,
    KIND_REPARENTED,
    KIND_RETYPED,
    KIND_REWIRED_SOURCE,
    KIND_REWIRED_TARGET,
    KIND_TRIGGERED_BY_EVENT_CHANGED,
    SCHEMA_VERSION,
    WARNING_LEVEL_WARNING,
    WARNING_NO_OVERLAPPING_IDS,
    WARNING_SCHEMA_MISMATCH,
)
from .schema import DiffResult, ParsedModel

__all__ = [
    "FLOW_FIELDS",
    "FLOW_KINDS",
    "LANE_FIELDS",
    "LANE_KINDS",
    "NODE_FIELDS",
    "NODE_KINDS",
    "PARTICIPANT_FIELDS",
    "PARTICIPANT_KINDS",
    "PROCESS_FIELDS",
    "PROCESS_KINDS",
    "build_arg_parser",
    "diff_files",
    "diff_models",
    "get_context",
    "get_element",
    "main",
]

NODE_KINDS = {
    "type": KIND_RETYPED,
    "name": KIND_RENAMED,
    "lane_id": KIND_LANE_MOVED,
    "parent": KIND_REPARENTED,
    "documentation": KIND_DOCUMENTATION_CHANGED,
    "default_flow": KIND_DEFAULT_FLOW_CHANGED,
    "gateway_direction": KIND_GATEWAY_DIRECTION_CHANGED,
    "event_definition": KIND_EVENT_DEFINITION_CHANGED,
    "loop": KIND_LOOP_CHANGED,
    "called_element": KIND_CALLED_ELEMENT_CHANGED,
    "attached_to": KIND_ATTACHED_TO_CHANGED,
    "cancel_activity": KIND_CANCEL_ACTIVITY_CHANGED,
    "event_detail": KIND_EVENT_DETAIL_CHANGED,
    "loop_detail": KIND_LOOP_DETAIL_CHANGED,
    "triggered_by_event": KIND_TRIGGERED_BY_EVENT_CHANGED,
}
NODE_FIELDS = tuple(NODE_KINDS)

FLOW_KINDS = {
    "type": KIND_RETYPED,
    "source": KIND_REWIRED_SOURCE,
    "target": KIND_REWIRED_TARGET,
    "name": KIND_RENAMED,
    "condition": KIND_CONDITION_CHANGED,
    "parent": KIND_REPARENTED,
}
FLOW_FIELDS = tuple(FLOW_KINDS)

LANE_KINDS = {"name": KIND_RENAMED, "parent_lane": KIND_REPARENTED}
LANE_FIELDS = tuple(LANE_KINDS)

PROCESS_KINDS = {"name": KIND_RENAMED}
PROCESS_FIELDS = tuple(PROCESS_KINDS)

PARTICIPANT_KINDS = {"name": KIND_RENAMED, "process_ref": KIND_REPARENTED}
PARTICIPANT_FIELDS = tuple(PARTICIPANT_KINDS)

_SIDE_ORDER = {"old": 0, "new": 1, "diff": 2}
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = _PROJECT_ROOT / "output"
FlowIndex = tuple[dict[str, list[str]], dict[str, list[str]]]


def diff_models(
    old: dict[str, Any], new: dict[str, Any], strict: bool = False
) -> DiffResult:
    old_nodes = old.get("nodes") or {}
    new_nodes = new.get("nodes") or {}
    old_flows = old.get("flows") or {}
    new_flows = new.get("flows") or {}
    old_lanes = old.get("lanes") or {}
    new_lanes = new.get("lanes") or {}
    old_processes = _process_index(old)
    new_processes = _process_index(new)
    old_participants = _participant_index(old)
    new_participants = _participant_index(new)

    old_flow_index = _build_flow_index(old)
    new_flow_index = _build_flow_index(new)

    nodes_added, nodes_removed, nodes_changed = _diff_nodes(
        old_nodes,
        new_nodes,
        old,
        new,
        old_flow_index,
        new_flow_index,
    )
    flows_added, flows_removed, flows_changed = _diff_flows(
        old_flows, new_flows, old, new
    )
    lanes_added, lanes_removed, lanes_changed = _diff_lanes(
        old_lanes, new_lanes
    )
    processes_added, processes_removed, processes_changed = _diff_processes(
        old_processes, new_processes
    )
    participants_added, participants_removed, participants_changed = (
        _diff_participants(old_participants, new_participants)
    )

    possible_renames = _possible_renames(
        old_nodes,
        new_nodes,
        [entry["node"]["id"] for entry in nodes_removed],
        [entry["node"]["id"] for entry in nodes_added],
    )

    identical = not any(
        (
            nodes_added,
            nodes_removed,
            nodes_changed,
            flows_added,
            flows_removed,
            flows_changed,
            lanes_added,
            lanes_removed,
            lanes_changed,
            processes_added,
            processes_removed,
            processes_changed,
            participants_added,
            participants_removed,
            participants_changed,
        )
    )

    warnings = _collect_warnings(old, new, old_nodes, new_nodes)
    blocking = [
        warning
        for warning in warnings
        if warning.get("level") == WARNING_LEVEL_WARNING
    ]
    if strict and blocking:
        raise BpmnParseError(_strict_message(blocking))

    summary = _build_summary(
        identical,
        nodes_added,
        nodes_removed,
        nodes_changed,
        flows_added,
        flows_removed,
        flows_changed,
        lanes_added,
        lanes_removed,
        lanes_changed,
        processes_added,
        processes_removed,
        processes_changed,
        participants_added,
        participants_removed,
        participants_changed,
        possible_renames,
        warnings,
        set(old_nodes) | set(new_nodes),
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "old_file": display_path(old.get("source_file") or ""),
        "new_file": display_path(new.get("source_file") or ""),
        "summary": summary,
        "nodes": {
            "added": nodes_added,
            "removed": nodes_removed,
            "changed": nodes_changed,
        },
        "flows": {
            "added": flows_added,
            "removed": flows_removed,
            "changed": flows_changed,
        },
        "lanes": {
            "added": lanes_added,
            "removed": lanes_removed,
            "changed": lanes_changed,
        },
        "processes": {
            "added": processes_added,
            "removed": processes_removed,
            "changed": processes_changed,
        },
        "participants": {
            "added": participants_added,
            "removed": participants_removed,
            "changed": participants_changed,
        },
        "warnings": warnings,
    }


def diff_files(
    old_path: str | Path, new_path: str | Path, strict: bool = False
) -> DiffResult:
    old_model = parse_bpmn(old_path, strict=strict)
    new_model = parse_bpmn(new_path, strict=strict)
    return diff_models(old_model, new_model, strict=strict)


def get_element(model: dict[str, Any], element_id: str) -> dict[str, Any] | None:
    for key in ("nodes", "flows", "lanes"):
        element = (model.get(key) or {}).get(element_id)
        if element is not None:
            return element

    for key in ("processes", "participants"):
        for element in model.get(key) or []:
            if element.get("id") == element_id:
                return element
    return None


def get_context(
    model: dict[str, Any],
    element_id: str,
    index: FlowIndex | None = None,
) -> dict[str, Any]:
    nodes = model.get("nodes") or {}
    flows = model.get("flows") or {}
    if element_id not in nodes:
        return {"incoming": [], "outgoing": []}

    if index is None:
        index = _build_flow_index(model)
    incoming_index, outgoing_index = index

    incoming: list[dict[str, str]] = []
    outgoing: list[dict[str, str]] = []
    for flow_id in incoming_index.get(element_id, []):
        flow = flows.get(flow_id)
        if flow is None:
            continue
        incoming.append(
            _neighbour(
                flow_id,
                flow.get("source", ""),
                nodes.get(flow.get("source", "")),
            )
        )
    for flow_id in outgoing_index.get(element_id, []):
        flow = flows.get(flow_id)
        if flow is None:
            continue
        outgoing.append(
            _neighbour(
                flow_id,
                flow.get("target", ""),
                nodes.get(flow.get("target", "")),
            )
        )
    return {"incoming": incoming, "outgoing": outgoing}


def _diff_nodes(
    old_nodes: dict[str, dict[str, Any]],
    new_nodes: dict[str, dict[str, Any]],
    old_model: dict[str, Any],
    new_model: dict[str, Any],
    old_flow_index: FlowIndex,
    new_flow_index: FlowIndex,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added_ids = sorted(set(new_nodes) - set(old_nodes))
    removed_ids = sorted(set(old_nodes) - set(new_nodes))
    changed_ids = sorted(set(old_nodes) & set(new_nodes))

    added = [
        {
            "node": new_nodes[node_id],
            "context": get_context(new_model, node_id, new_flow_index),
        }
        for node_id in added_ids
    ]
    removed = [
        {
            "node": old_nodes[node_id],
            "context": get_context(old_model, node_id, old_flow_index),
        }
        for node_id in removed_ids
    ]
    changed = _changed_entries(
        old_nodes, new_nodes, changed_ids, NODE_FIELDS, NODE_KINDS
    )
    for entry in changed:
        entry["context"] = get_context(new_model, entry["id"], new_flow_index)
    return added, removed, changed


def _diff_flows(
    old_flows: dict[str, dict[str, Any]],
    new_flows: dict[str, dict[str, Any]],
    old_model: dict[str, Any],
    new_model: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added_ids = sorted(set(new_flows) - set(old_flows))
    removed_ids = sorted(set(old_flows) - set(new_flows))
    changed_ids = sorted(set(old_flows) & set(new_flows))

    added = [
        {
            "flow": new_flows[flow_id],
            "endpoints": _flow_endpoints(new_model, new_flows[flow_id]),
        }
        for flow_id in added_ids
    ]
    removed = [
        {
            "flow": old_flows[flow_id],
            "endpoints": _flow_endpoints(old_model, old_flows[flow_id]),
        }
        for flow_id in removed_ids
    ]
    changed = _changed_entries(
        old_flows, new_flows, changed_ids, FLOW_FIELDS, FLOW_KINDS
    )
    for entry in changed:
        entry["endpoints"] = _flow_endpoints(new_model, new_flows[entry["id"]])
        entry["endpoints_old"] = _flow_endpoints(old_model, old_flows[entry["id"]])
    return added, removed, changed


def _diff_lanes(
    old_lanes: dict[str, dict[str, Any]],
    new_lanes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added_ids = sorted(set(new_lanes) - set(old_lanes))
    removed_ids = sorted(set(old_lanes) - set(new_lanes))
    changed_ids = sorted(set(old_lanes) & set(new_lanes))
    added = [new_lanes[lane_id] for lane_id in added_ids]
    removed = [old_lanes[lane_id] for lane_id in removed_ids]
    changed = _changed_entries(
        old_lanes, new_lanes, changed_ids, LANE_FIELDS, LANE_KINDS
    )
    return added, removed, changed


def _diff_processes(
    old_processes: dict[str, dict[str, str]],
    new_processes: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added_ids = sorted(set(new_processes) - set(old_processes))
    removed_ids = sorted(set(old_processes) - set(new_processes))
    changed_ids = sorted(set(old_processes) & set(new_processes))
    added = [new_processes[process_id] for process_id in added_ids]
    removed = [old_processes[process_id] for process_id in removed_ids]
    changed = _changed_entries(
        old_processes,
        new_processes,
        changed_ids,
        PROCESS_FIELDS,
        PROCESS_KINDS,
    )
    return added, removed, changed


def _diff_participants(
    old_participants: dict[str, dict[str, str]],
    new_participants: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    added_ids = sorted(set(new_participants) - set(old_participants))
    removed_ids = sorted(set(old_participants) - set(new_participants))
    changed_ids = sorted(set(old_participants) & set(new_participants))
    added = [new_participants[participant_id] for participant_id in added_ids]
    removed = [
        old_participants[participant_id] for participant_id in removed_ids
    ]
    changed = _changed_entries(
        old_participants,
        new_participants,
        changed_ids,
        PARTICIPANT_FIELDS,
        PARTICIPANT_KINDS,
    )
    return added, removed, changed


def _process_index(model: ParsedModel | dict[str, Any]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for process in model.get("processes") or []:
        process_id = process.get("id", "")
        if process_id:
            index[process_id] = {
                "id": process_id,
                "name": process.get("name", ""),
            }
    return index


def _participant_index(
    model: ParsedModel | dict[str, Any]
) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for participant in model.get("participants") or []:
        participant_id = participant.get("id", "")
        if participant_id:
            index[participant_id] = {
                "id": participant_id,
                "name": participant.get("name", ""),
                "process_ref": participant.get("process_ref", ""),
            }
    return index


def _changed_entries(
    old_elements: dict[str, dict[str, Any]],
    new_elements: dict[str, dict[str, Any]],
    element_ids: Iterable[str],
    fields: tuple[str, ...],
    kinds: dict[str, str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for element_id in element_ids:
        changed_fields, changed_kinds = _compare_fields(
            old_elements[element_id],
            new_elements[element_id],
            fields,
            kinds,
        )
        if not changed_fields:
            continue
        entries.append(
            {
                "id": element_id,
                "kinds": changed_kinds,
                "fields": changed_fields,
            }
        )
    return entries


def _compare_fields(
    old_element: dict[str, Any],
    new_element: dict[str, Any],
    fields: tuple[str, ...],
    kinds: dict[str, str],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    changed: dict[str, dict[str, str]] = {}
    labels: set[str] = set()
    for field in fields:
        old_value = old_element.get(field, "")
        new_value = new_element.get(field, "")
        if old_value == new_value:
            continue
        changed[field] = {"old": old_value, "new": new_value}
        labels.add(kinds[field])
    return changed, sorted(labels)


def _summary_counts(
    added: list[Any], removed: list[Any], changed: list[Any]
) -> dict[str, int]:
    return {
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
    }


def _build_summary(
    identical: bool,
    nodes_added: list[Any],
    nodes_removed: list[Any],
    nodes_changed: list[Any],
    flows_added: list[Any],
    flows_removed: list[Any],
    flows_changed: list[Any],
    lanes_added: list[Any],
    lanes_removed: list[Any],
    lanes_changed: list[Any],
    processes_added: list[Any],
    processes_removed: list[Any],
    processes_changed: list[Any],
    participants_added: list[Any],
    participants_removed: list[Any],
    participants_changed: list[Any],
    possible_renames: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    node_ids: set[str],
) -> dict[str, Any]:
    kinds = Counter()
    for group in (
        nodes_changed,
        flows_changed,
        lanes_changed,
        processes_changed,
        participants_changed,
    ):
        for entry in group:
            kinds.update(entry.get("kinds") or [])

    return {
        "identical": identical,
        "nodes": _summary_counts(nodes_added, nodes_removed, nodes_changed),
        "flows": _summary_counts(flows_added, flows_removed, flows_changed),
        "lanes": _summary_counts(lanes_added, lanes_removed, lanes_changed),
        "processes": _summary_counts(
            processes_added, processes_removed, processes_changed
        ),
        "participants": _summary_counts(
            participants_added, participants_removed, participants_changed
        ),
        "possible_renames": possible_renames,
        "kinds": dict(sorted(kinds.items())),
        "touched_node_ids": _touched_node_ids(
            nodes_added,
            nodes_removed,
            nodes_changed,
            flows_added,
            flows_removed,
            flows_changed,
            node_ids,
        ),
        "warnings": len(warnings),
    }


def _touched_node_ids(
    nodes_added: list[dict[str, Any]],
    nodes_removed: list[dict[str, Any]],
    nodes_changed: list[dict[str, Any]],
    flows_added: list[dict[str, Any]],
    flows_removed: list[dict[str, Any]],
    flows_changed: list[dict[str, Any]],
    node_ids: set[str],
) -> list[str]:
    touched: set[str] = set()
    for entry in nodes_added + nodes_removed:
        node_id = entry["node"].get("id", "")
        if node_id:
            touched.add(node_id)
    for entry in nodes_changed:
        if entry.get("id"):
            touched.add(entry["id"])

    for entry in flows_added + flows_removed:
        flow = entry["flow"]
        for key in ("source", "target"):
            if flow.get(key) in node_ids:
                touched.add(flow[key])
    for entry in flows_changed:
        for key in ("endpoints", "endpoints_old"):
            endpoints = entry.get(key) or {}
            for side in ("source", "target"):
                node_id = (endpoints.get(side) or {}).get("id", "")
                if node_id in node_ids:
                    touched.add(node_id)

    return sorted(touched)


def _node_summary(node_id: str, node: dict[str, Any] | None) -> dict[str, str]:
    return {
        "id": node_id,
        "type": node.get("type", "") if node else "",
        "name": node.get("name", "") if node else "",
    }


def _flow_endpoints(
    model: dict[str, Any], flow: dict[str, Any]
) -> dict[str, dict[str, str]]:
    nodes = model.get("nodes") or {}
    source = flow.get("source", "")
    target = flow.get("target", "")
    return {
        "source": _node_summary(source, nodes.get(source)),
        "target": _node_summary(target, nodes.get(target)),
    }


def _neighbour(
    flow_id: str, node_id: str, node: dict[str, Any] | None
) -> dict[str, str]:
    return {
        "flow": flow_id,
        "node": node_id,
        "name": node.get("name", "") if node else "",
        "type": node.get("type", "") if node else "",
    }


def _build_flow_index(model: dict[str, Any]) -> FlowIndex:
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    flows = model.get("flows") or {}
    for flow_id in sorted(flows):
        flow = flows[flow_id]
        outgoing[flow.get("source", "")].append(flow_id)
        incoming[flow.get("target", "")].append(flow_id)
    return dict(incoming), dict(outgoing)


def _possible_renames(
    old_nodes: dict[str, dict[str, Any]],
    new_nodes: dict[str, dict[str, Any]],
    removed_ids: list[str],
    added_ids: list[str],
) -> list[dict[str, Any]]:
    def key(node: dict[str, Any]) -> tuple[str, str, str]:
        return (
            node.get("type", ""),
            node.get("name", ""),
            node.get("lane_id", ""),
        )

    removed: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    added: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for node_id in removed_ids:
        if old_nodes[node_id].get("name"):
            removed[key(old_nodes[node_id])].append(node_id)
    for node_id in added_ids:
        if new_nodes[node_id].get("name"):
            added[key(new_nodes[node_id])].append(node_id)

    renames: list[dict[str, Any]] = []
    for candidate, remapped in sorted(
        removed.items(), key=lambda item: item[1][0]
    ):
        candidates = added.get(candidate, [])
        if len(remapped) != 1 or len(candidates) != 1:
            continue
        renames.append(
            {
                "removed": remapped[0],
                "added": candidates[0],
                "basis": ["type", "name", "lane"],
            }
        )
    return renames


def _collect_warnings(
    old: dict[str, Any],
    new: dict[str, Any],
    old_nodes: dict[str, Any],
    new_nodes: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for side, model in (("old", old), ("new", new)):
        for warning in model.get("warnings") or []:
            warnings.append(
                {
                    "side": side,
                    "code": warning.get("code", ""),
                    "level": warning.get("level", WARNING_LEVEL_WARNING),
                    "message": warning.get("message", ""),
                    "element_id": warning.get("element_id", ""),
                }
            )

    old_schema = old.get("schema_version", "")
    new_schema = new.get("schema_version", "")
    if old_schema != new_schema:
        warnings.append(
            {
                "side": "diff",
                "code": WARNING_SCHEMA_MISMATCH,
                "level": WARNING_LEVEL_WARNING,
                "message": (
                    "The two models use different schema versions: "
                    f"'{old_schema}' and '{new_schema}'"
                ),
                "element_id": "",
            }
        )

    if old_nodes and new_nodes and not (set(old_nodes) & set(new_nodes)):
        warnings.append(
            {
                "side": "diff",
                "code": WARNING_NO_OVERLAPPING_IDS,
                "level": WARNING_LEVEL_WARNING,
                "message": "The two models have no node IDs in common",
                "element_id": "",
            }
        )

    warnings.sort(
        key=lambda warning: (
            _SIDE_ORDER.get(warning["side"], 3),
            warning["element_id"],
            warning["code"],
            warning["message"],
        )
    )
    return warnings


def _strict_message(warnings: list[dict[str, Any]]) -> str:
    details = "; ".join(
        f"{warning['side']}:{warning['code']} "
        f"({warning['element_id'] or 'no ID'})"
        for warning in warnings
    )
    return f"strict diff mode found {len(warnings)} warnings: {details}"


def _node_line(node: dict[str, Any]) -> str:
    return f"- `{node['id']}` ({node['type']}) {node['name']}".rstrip()


def _flow_line(entry: dict[str, Any]) -> str:
    flow = entry["flow"]
    endpoints = entry.get("endpoints") or {}

    def label(side: str) -> str:
        node = endpoints.get(side) or {}
        node_id = node.get("id", "")
        name = node.get("name", "")
        return f"{node_id} ({name})" if name else node_id

    return (
        f"- `{flow['id']}` ({flow['type']}) {label('source')} -> "
        f"{label('target')}"
    ).rstrip()


def _format_changed(entries: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for entry in entries:
        lines.append(f"- `{entry['id']}`: {', '.join(entry['kinds'])}")
        for field, values in entry["fields"].items():
            lines.append(f"  - {field}: `{values['old']}` -> `{values['new']}`")
    return lines


def _format_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# BPMN Diff",
        "",
        f"- Old file: `{result['old_file']}`",
        f"- New file: `{result['new_file']}`",
        f"- Identical: {'yes' if summary['identical'] else 'no'}",
        "",
        "## Summary",
        "",
        "| Category | Added | Removed | Changed |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (
        ("nodes", "Node"),
        ("flows", "Flow"),
        ("lanes", "Lane"),
        ("processes", "Processes"),
        ("participants", "Participants"),
    ):
        counts = summary[key]
        lines.append(
            f"| {label} | {counts['added']} | {counts['removed']} | "
            f"{counts['changed']} |"
        )

    if summary.get("kinds"):
        lines.extend(["", "## Change Kinds"])
        lines.extend(
            f"- {kind}: {count}" for kind, count in summary["kinds"].items()
        )

    sections = (
        (
            "Node",
            result["nodes"]["added"],
            result["nodes"]["removed"],
            result["nodes"]["changed"],
            lambda entry: _node_line(entry["node"]),
        ),
        (
            "Flow",
            result["flows"]["added"],
            result["flows"]["removed"],
            result["flows"]["changed"],
            _flow_line,
        ),
        (
            "Lane",
            result["lanes"]["added"],
            result["lanes"]["removed"],
            result["lanes"]["changed"],
            lambda entry: f"- `{entry['id']}` {entry['name']}".rstrip(),
        ),
        (
            "Processes",
            result["processes"]["added"],
            result["processes"]["removed"],
            result["processes"]["changed"],
            lambda entry: f"- `{entry['id']}` {entry['name']}".rstrip(),
        ),
        (
            "Participants",
            result["participants"]["added"],
            result["participants"]["removed"],
            result["participants"]["changed"],
            lambda entry: f"- `{entry['id']}` {entry['name']}".rstrip(),
        ),
    )

    for title, added, removed, changed, formatter in sections:
        if not (added or removed or changed):
            continue
        lines.extend(["", f"## {title}"])
        if added:
            lines.extend(["", "### Added"])
            lines.extend(formatter(entry) for entry in added)
        if removed:
            lines.extend(["", "### Removed"])
            lines.extend(formatter(entry) for entry in removed)
        if changed:
            lines.extend(["", "### Changed"])
            lines.extend(_format_changed(changed))

    renames = summary["possible_renames"]
    if renames:
        lines.extend(["", "## Possible ID Renames"])
        lines.extend(
            f"- `{entry['removed']}` -> `{entry['added']}`" for entry in renames
        )

    warnings = result["warnings"]
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(
            f"- [{warning['side']}] [{warning.get('level', 'warning')}] "
            f"{warning['code']} "
            f"({warning['element_id'] or 'no ID'}): {warning['message']}"
            for warning in warnings
        )

    return "\n".join(lines)


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")


def _write_output(text: str, suffix: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = OUTPUT_DIR / f"{timestamp}{suffix}"
    _write_text(path, text)
    return path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.bpmn_diff",
        description="Compare two BPMN 2.0 files.",
        epilog="Exit codes: 0 success, 1 unexpected error, 2 parse/strict failure.",
    )
    parser.add_argument("old", type=Path, help="old BPMN file")
    parser.add_argument("new", type=Path, help="new BPMN file")
    format_group = parser.add_mutually_exclusive_group(required=True)
    format_group.add_argument(
        "--md", action="store_true", help="write a Markdown result"
    )
    format_group.add_argument(
        "--json", action="store_true", help="write a JSON result"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warning-level findings as errors",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print a full traceback on unexpected errors",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=SCHEMA_VERSION,
        help="print the output schema version",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    force_utf8(sys.stdout)
    force_utf8(sys.stderr)

    try:
        result = diff_files(args.old, args.new, strict=args.strict)
    except BpmnParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if args.debug:
            traceback.print_exc()
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.md:
        text = _format_markdown(result)
    else:
        text = json.dumps(result, ensure_ascii=False, indent=2)

    suffix = ".md" if args.md else ".json"
    try:
        output_path = _write_output(text, suffix)
    except OSError as exc:
        print(f"Error: unable to write output: {exc}", file=sys.stderr)
        return 1

    print(f"Output saved to {output_path.relative_to(_PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
