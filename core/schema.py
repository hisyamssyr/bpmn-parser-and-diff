from __future__ import annotations

from typing import Any, TypedDict

__all__ = [
    "DiffResult",
    "FlowDict",
    "LaneDict",
    "NodeDict",
    "ParsedModel",
    "ParticipantDict",
    "ProcessDict",
    "WarningDict",
]


class WarningDict(TypedDict):
    code: str
    message: str
    element_id: str
    level: str


class NodeDict(TypedDict):
    id: str
    type: str
    name: str
    lane: str
    lane_id: str
    lane_path: list[str]
    parent: str
    process: str
    documentation: str
    default_flow: str
    gateway_direction: str
    event_definition: str
    loop: str
    called_element: str
    attached_to: str
    cancel_activity: str
    event_detail: str
    loop_detail: str
    triggered_by_event: str


class FlowDict(TypedDict):
    id: str
    type: str
    source: str
    target: str
    name: str
    condition: str
    parent: str
    process: str


class LaneDict(TypedDict):
    id: str
    name: str
    parent_lane: str
    process: str


class ProcessDict(TypedDict):
    id: str
    name: str


class ParticipantDict(TypedDict):
    id: str
    name: str
    process_ref: str


class ParsedModel(TypedDict):
    schema_version: str
    source_file: str
    processes: list[ProcessDict]
    participants: list[ParticipantDict]
    lanes: dict[str, LaneDict]
    nodes: dict[str, NodeDict]
    flows: dict[str, FlowDict]
    warnings: list[WarningDict]


class DiffResult(TypedDict):
    schema_version: str
    old_file: str
    new_file: str
    summary: dict[str, Any]
    nodes: dict[str, list[dict[str, Any]]]
    flows: dict[str, list[dict[str, Any]]]
    lanes: dict[str, list[dict[str, Any]]]
    processes: dict[str, list[dict[str, Any]]]
    participants: dict[str, list[dict[str, Any]]]
    warnings: list[dict[str, Any]]
