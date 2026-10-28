from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .bpmn_parser import SCHEMA_VERSION, BpmnParseError, parse_bpmn

NODE_FIELDS = (
    "type",
    "name",
    "lane_id",
    "parent",
    "documentation",
    "default_flow",
    "gateway_direction",
    "event_definition",
    "loop",
    "called_element",
    "attached_to",
    "cancel_activity",
)

NODE_KINDS = {
    "type": "retyped",
    "name": "renamed",
    "lane_id": "lane_moved",
    "parent": "reparented",
    "documentation": "documentation_changed",
    "default_flow": "default_flow_changed",
    "gateway_direction": "gateway_direction_changed",
    "event_definition": "event_definition_changed",
    "loop": "loop_changed",
    "called_element": "called_element_changed",
    "attached_to": "attached_to_changed",
    "cancel_activity": "cancel_activity_changed",
}

FLOW_FIELDS = ("type", "source", "target", "name", "condition", "parent")

FLOW_KINDS = {
    "type": "retyped",
    "source": "rewired_source",
    "target": "rewired_target",
    "name": "renamed",
    "condition": "condition_changed",
    "parent": "reparented",
}

LANE_FIELDS = ("name", "parent_lane")
LANE_KINDS = {"name": "renamed", "parent_lane": "reparented"}

PROCESS_FIELDS = ("name",)
PROCESS_KINDS = {"name": "renamed"}

_SIDE_ORDER = {"old": 0, "new": 1, "diff": 2}


def diff_models(
    old: dict[str, Any], new: dict[str, Any], strict: bool = False
) -> dict[str, Any]:
    old_nodes = old.get("nodes") or {}
    new_nodes = new.get("nodes") or {}
    old_flows = old.get("flows") or {}
    new_flows = new.get("flows") or {}
    old_lanes = old.get("lanes") or {}
    new_lanes = new.get("lanes") or {}
    old_processes = _process_index(old)
    new_processes = _process_index(new)

    node_added_ids = sorted(set(new_nodes) - set(old_nodes))
    node_removed_ids = sorted(set(old_nodes) - set(new_nodes))
    node_changed_ids = sorted(set(old_nodes) & set(new_nodes))

    flow_added_ids = sorted(set(new_flows) - set(old_flows))
    flow_removed_ids = sorted(set(old_flows) - set(new_flows))
    flow_changed_ids = sorted(set(old_flows) & set(new_flows))

    lane_added_ids = sorted(set(new_lanes) - set(old_lanes))
    lane_removed_ids = sorted(set(old_lanes) - set(new_lanes))
    lane_changed_ids = sorted(set(old_lanes) & set(new_lanes))

    process_added_ids = sorted(set(new_processes) - set(old_processes))
    process_removed_ids = sorted(set(old_processes) - set(new_processes))
    process_changed_ids = sorted(set(old_processes) & set(new_processes))

    nodes_added = [
        {"node": new_nodes[node_id], "context": get_context(new, node_id)}
        for node_id in node_added_ids
    ]
    nodes_removed = [
        {"node": old_nodes[node_id], "context": get_context(old, node_id)}
        for node_id in node_removed_ids
    ]
    nodes_changed = _changed_entries(
        old_nodes, new_nodes, node_changed_ids, NODE_FIELDS, NODE_KINDS
    )
    for entry in nodes_changed:
        entry["context"] = get_context(new, entry["id"])

    flows_added = [
        {
            "flow": new_flows[flow_id],
            "endpoints": _flow_endpoints(new, new_flows[flow_id]),
        }
        for flow_id in flow_added_ids
    ]
    flows_removed = [
        {
            "flow": old_flows[flow_id],
            "endpoints": _flow_endpoints(old, old_flows[flow_id]),
        }
        for flow_id in flow_removed_ids
    ]
    flows_changed = _changed_entries(
        old_flows, new_flows, flow_changed_ids, FLOW_FIELDS, FLOW_KINDS
    )
    for entry in flows_changed:
        entry["endpoints"] = _flow_endpoints(new, new_flows[entry["id"]])
        entry["endpoints_old"] = _flow_endpoints(old, old_flows[entry["id"]])

    lanes_added = [new_lanes[lane_id] for lane_id in lane_added_ids]
    lanes_removed = [old_lanes[lane_id] for lane_id in lane_removed_ids]
    lanes_changed = _changed_entries(
        old_lanes, new_lanes, lane_changed_ids, LANE_FIELDS, LANE_KINDS
    )

    processes_added = [new_processes[process_id] for process_id in process_added_ids]
    processes_removed = [
        old_processes[process_id] for process_id in process_removed_ids
    ]
    processes_changed = _changed_entries(
        old_processes,
        new_processes,
        process_changed_ids,
        PROCESS_FIELDS,
        PROCESS_KINDS,
    )

    possible_renames = _possible_renames(
        old_nodes, new_nodes, node_removed_ids, node_added_ids
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
        )
    )

    warnings = _collect_warnings(old, new, old_nodes, new_nodes)

    if strict and warnings:
        details = "; ".join(
            f"{warning['side']}:{warning['code']} "
            f"({warning['element_id'] or 'no ID'})"
            for warning in warnings
        )
        raise BpmnParseError(
            f"Strict diff mode found {len(warnings)} warnings: {details}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "old_file": old.get("source_file") or "",
        "new_file": new.get("source_file") or "",
        "summary": {
            "identical": identical,
            "nodes": _summary_counts(nodes_added, nodes_removed, nodes_changed),
            "flows": _summary_counts(flows_added, flows_removed, flows_changed),
            "lanes": _summary_counts(lanes_added, lanes_removed, lanes_changed),
            "processes": _summary_counts(
                processes_added, processes_removed, processes_changed
            ),
            "possible_renames": possible_renames,
        },
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
        "warnings": warnings,
    }


def diff_files(
    old_path: str | Path, new_path: str | Path, strict: bool = False
) -> dict[str, Any]:
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


def get_context(model: dict[str, Any], element_id: str) -> dict[str, Any]:
    nodes = model.get("nodes") or {}
    flows = model.get("flows") or {}
    incoming: list[dict[str, str]] = []
    outgoing: list[dict[str, str]] = []

    if element_id in nodes:
        for flow_id in sorted(flows):
            flow = flows[flow_id]
            if flow.get("target") == element_id:
                incoming.append(
                    _neighbour(
                        flow_id,
                        flow.get("source", ""),
                        nodes.get(flow.get("source", "")),
                    )
                )
            if flow.get("source") == element_id:
                outgoing.append(
                    _neighbour(
                        flow_id,
                        flow.get("target", ""),
                        nodes.get(flow.get("target", "")),
                    )
                )

    return {"incoming": incoming, "outgoing": outgoing}


def diff_dirs(old_dir: str | Path, new_dir: str | Path) -> dict[str, Any]:
    old_path = Path(old_dir)
    new_path = Path(new_dir)
    if not old_path.is_dir():
        raise BpmnParseError(f"Directory not found: '{old_path}'")
    if not new_path.is_dir():
        raise BpmnParseError(f"Directory not found: '{new_path}'")

    old_files = {
        path.name: path for path in sorted(old_path.glob("*.bpmn")) if path.is_file()
    }
    new_files = {
        path.name: path for path in sorted(new_path.glob("*.bpmn")) if path.is_file()
    }

    added = sorted(set(new_files) - set(old_files))
    removed = sorted(set(old_files) - set(new_files))
    changed: list[dict[str, Any]] = []
    for name in sorted(set(old_files) & set(new_files)):
        result = diff_files(old_files[name], new_files[name])
        if not result["summary"]["identical"]:
            changed.append(result)

    return {
        "schema_version": SCHEMA_VERSION,
        "old_dir": str(old_path),
        "new_dir": str(new_path),
        "files": {"added": added, "removed": removed, "changed": changed},
    }


def _process_index(model: dict[str, Any]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for process in model.get("processes") or []:
        process_id = process.get("id", "")
        if process_id:
            index[process_id] = {
                "id": process_id,
                "name": process.get("name", ""),
            }

    for participant in model.get("participants") or []:
        participant_id = participant.get("id", "")
        if participant_id and participant_id not in index:
            index[participant_id] = {
                "id": participant_id,
                "name": participant.get("name", ""),
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


def _possible_renames(
    old_nodes: dict[str, dict[str, Any]],
    new_nodes: dict[str, dict[str, Any]],
    removed_ids: list[str],
    added_ids: list[str],
) -> list[dict[str, Any]]:
    remaining = set(added_ids)
    renames: list[dict[str, Any]] = []
    for removed_id in removed_ids:
        removed = old_nodes[removed_id]
        for added_id in sorted(remaining):
            added = new_nodes[added_id]
            if (
                removed.get("type") == added.get("type")
                and removed.get("name") == added.get("name")
                and removed.get("lane_id") == added.get("lane_id")
            ):
                renames.append(
                    {
                        "removed": removed_id,
                        "added": added_id,
                        "basis": ["type", "name", "lane"],
                    }
                )
                remaining.remove(added_id)
                break
    return renames


def _collect_warnings(
    old: dict[str, Any],
    new: dict[str, Any],
    old_nodes: dict[str, Any],
    new_nodes: dict[str, Any],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for side, model in (("old", old), ("new", new)):
        for warning in model.get("warnings") or []:
            warnings.append(
                {
                    "side": side,
                    "code": warning.get("code", ""),
                    "message": warning.get("message", ""),
                    "element_id": warning.get("element_id", ""),
                }
            )

    if old_nodes and new_nodes and not (set(old_nodes) & set(new_nodes)):
        warnings.append(
            {
                "side": "diff",
                "code": "NO_OVERLAPPING_IDS",
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


def _force_utf8(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        pass


def _node_line(node: dict[str, Any]) -> str:
    return f"- `{node['id']}` ({node['type']}) {node['name']}".rstrip()


def _flow_line(flow: dict[str, Any]) -> str:
    return (
        f"- `{flow['id']}` ({flow['type']}) {flow['source']} -> {flow['target']}"
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
    ):
        counts = summary[key]
        lines.append(
            f"| {label} | {counts['added']} | {counts['removed']} | "
            f"{counts['changed']} |"
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
            lambda entry: _flow_line(entry["flow"]),
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
            f"- [{warning['side']}] {warning['code']} "
            f"({warning['element_id'] or 'no ID'}): {warning['message']}"
            for warning in warnings
        )

    return "\n".join(lines)


def _write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m core.bpmn_diff",
        description="Compare two BPMN 2.0 files.",
    )
    parser.add_argument("old", type=Path, help="old BPMN file")
    parser.add_argument("new", type=Path, help="new BPMN file")
    parser.add_argument(
        "--md", action="store_true", help="show a Markdown summary"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat all warnings as errors",
    )
    parser.add_argument("--out", type=Path, default=None, help="write the result to a file")
    args = parser.parse_args(argv)

    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)

    try:
        result = diff_files(args.old, args.new, strict=args.strict)
    except BpmnParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    text = (
        _format_markdown(result)
        if args.md
        else json.dumps(result, ensure_ascii=False, indent=2)
    )

    if args.out is not None:
        try:
            _write_text(args.out, text)
        except OSError as exc:
            print(f"Error: unable to write '{args.out}': {exc}", file=sys.stderr)
            return 1
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
