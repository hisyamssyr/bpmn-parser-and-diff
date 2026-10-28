"""Helper untuk membangun model BPMN minimal di unit test."""

from __future__ import annotations

from typing import Any


def make_node(node_id: str, **overrides: Any) -> dict[str, Any]:
    node = {
        "id": node_id,
        "type": "task",
        "name": node_id,
        "lane": "",
        "lane_id": "",
        "lane_path": [],
        "parent": "P",
        "process": "P",
        "documentation": "",
        "default_flow": "",
        "gateway_direction": "",
        "event_definition": "",
        "loop": "",
        "called_element": "",
        "attached_to": "",
        "cancel_activity": "",
    }
    node.update(overrides)
    return node


def make_flow(
    flow_id: str, source: str, target: str, **overrides: Any
) -> dict[str, Any]:
    flow = {
        "id": flow_id,
        "type": "sequence",
        "source": source,
        "target": target,
        "name": "",
        "condition": "",
        "parent": "P",
        "process": "P",
    }
    flow.update(overrides)
    return flow


def make_lane(
    lane_id: str, name: str, parent_lane: str = "", process: str = "P"
) -> dict[str, Any]:
    return {
        "id": lane_id,
        "name": name,
        "parent_lane": parent_lane,
        "process": process,
    }


def make_model(
    *,
    nodes: dict[str, dict[str, Any]] | None = None,
    flows: dict[str, dict[str, Any]] | None = None,
    lanes: dict[str, dict[str, Any]] | None = None,
    processes: list[dict[str, Any]] | None = None,
    participants: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    source_file: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "source_file": source_file,
        "processes": processes
        if processes is not None
        else [{"id": "P", "name": "Proses"}],
        "participants": participants or [],
        "lanes": lanes or {},
        "nodes": nodes or {},
        "flows": flows or {},
        "warnings": warnings or [],
    }
