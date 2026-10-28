from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

BPMN_NAMESPACE = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SCHEMA_VERSION = "1.0"
MAX_FILE_SIZE = 20 * 1024 * 1024

NODE_TYPES = frozenset(
    {
        "task",
        "userTask",
        "serviceTask",
        "manualTask",
        "scriptTask",
        "businessRuleTask",
        "sendTask",
        "receiveTask",
        "subProcess",
        "callActivity",
        "startEvent",
        "endEvent",
        "intermediateCatchEvent",
        "intermediateThrowEvent",
        "boundaryEvent",
        "exclusiveGateway",
        "parallelGateway",
        "inclusiveGateway",
        "eventBasedGateway",
        "complexGateway",
    }
)

_IGNORED_FLOW_ELEMENTS = frozenset(
    {
        "laneSet",
        "lane",
        "childLaneSet",
        "flowNodeRef",
        "documentation",
        "extensionElements",
        "incoming",
        "outgoing",
        "conditionExpression",
        "standardLoopCharacteristics",
        "multiInstanceLoopCharacteristics",
    }
)

_IGNORED_DEFINITIONS_ELEMENTS = frozenset(
    {"documentation", "extensionElements", "import"}
)
_IGNORED_COLLABORATION_ELEMENTS = frozenset({"documentation", "extensionElements"})

_EVENT_DEFINITION_SUFFIX = "EventDefinition"
_EVENT_DEFINITION_ALIASES = {"compensate": "compensation"}

_XML_DECLARATION_RE = re.compile(r"^\s*<\?xml[^>]*\?>")
_WHITESPACE_RE = re.compile(r"\s+")


class BpmnParseError(Exception):
    pass


def parse_bpmn(path: str | Path, strict: bool = False) -> dict[str, Any]:
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise BpmnParseError(
            f"Unable to read file '{file_path}': {reason}"
        ) from exc

    if size > MAX_FILE_SIZE:
        raise BpmnParseError(
            f"File '{file_path}' is {size} bytes and exceeds the 20 MB limit"
        )

    etree = _element_tree()
    try:
        tree = etree.parse(str(file_path), forbid_dtd=True)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise BpmnParseError(
            f"Unable to read file '{file_path}': {reason}"
        ) from exc
    except Exception as exc:
        raise BpmnParseError(_format_xml_error(file_path, exc)) from exc

    return _parse_root(tree.getroot(), str(path), strict)


def parse_bpmn_string(xml_text: str, strict: bool = False) -> dict[str, Any]:
    if not isinstance(xml_text, str):
        raise BpmnParseError("parse_bpmn_string requires XML content as a str")

    text = xml_text.lstrip("\ufeff")
    text = _XML_DECLARATION_RE.sub("", text, count=1)
    if not text.strip():
        raise BpmnParseError("XML content is empty")

    etree = _element_tree()
    try:
        root = etree.fromstring(text.encode("utf-8"), forbid_dtd=True)
    except UnicodeEncodeError as exc:
        raise BpmnParseError("XML content cannot be encoded as UTF-8") from exc
    except Exception as exc:
        raise BpmnParseError(f"Unable to parse XML: {exc}") from exc

    return _parse_root(root, "", strict)


def _element_tree() -> Any:
    try:
        from defusedxml import ElementTree as etree
    except ImportError as exc:
        raise BpmnParseError(
            "The 'defusedxml' library is not installed. "
            "Run: pip install -r requirements.txt"
        ) from exc
    return etree


def _parse_root(root: Any, source_file: str, strict: bool) -> dict[str, Any]:
    if not _is_bpmn(root) or _local_name(root.tag) != "definitions":
        location = f" in '{source_file}'" if source_file else ""
        raise BpmnParseError(f"XML root{location} is not a BPMN 2.0 definitions element")

    parser = _Parser(source_file)
    parser.parse(root)

    if strict and parser.warnings:
        raise BpmnParseError(_strict_message(parser.warnings, source_file))

    return parser.model()


def _strict_message(warnings: list[dict[str, str]], source_file: str) -> str:
    prefix = f"{source_file}: " if source_file else ""
    details = "; ".join(
        f"{warning['code']} ({warning['element_id'] or 'no ID'})"
        for warning in warnings
    )
    return f"{prefix}strict mode found {len(warnings)} warnings: {details}"


def _format_xml_error(path: Path | str, exc: Exception) -> str:
    position = getattr(exc, "position", None)
    if position:
        return (
            f"Invalid XML in '{path}' at line {position[0]}, "
            f"column {position[1]}: {exc}"
        )
    return f"Unable to parse XML in '{path}': {exc}"


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFC", value)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _clean_ref(value: str | None) -> str:
    return value.strip() if value else ""


def _tag_parts(tag: Any) -> tuple[str, str]:
    if not isinstance(tag, str):
        return "", ""
    if tag.startswith("{"):
        namespace, _, local = tag[1:].partition("}")
        return namespace, local
    return "", tag


def _local_name(tag: Any) -> str:
    return _tag_parts(tag)[1]


def _is_bpmn(element: Any) -> bool:
    return _tag_parts(element.tag)[0] == BPMN_NAMESPACE


def _bpmn_children(element: Any) -> list[Any]:
    return [child for child in element if _is_bpmn(child)]


class _Parser:
    def __init__(self, source_file: str) -> None:
        self.source_file = source_file
        self.processes: list[dict[str, str]] = []
        self.participants: list[dict[str, str]] = []
        self.lanes: dict[str, dict[str, Any]] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.flows: dict[str, dict[str, str]] = {}
        self.warnings: list[dict[str, str]] = []

        self._seen_ids: dict[str, str] = {}
        self._lane_refs: list[tuple[str, list[str]]] = []

    def parse(self, root: Any) -> None:
        for child in _bpmn_children(root):
            local = _local_name(child.tag)
            if local == "process":
                self._parse_process(child)
            elif local == "collaboration":
                self._parse_collaboration(child)
            elif local in _IGNORED_DEFINITIONS_ELEMENTS:
                continue
            else:
                self._warn_unknown(child, local)

        self._assign_lanes()
        self._check_dangling_references()

    def model(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "source_file": self.source_file,
            "processes": self.processes,
            "participants": self.participants,
            "lanes": self.lanes,
            "nodes": self.nodes,
            "flows": self.flows,
            "warnings": self.warnings,
        }

    def _warn(self, code: str, message: str, element_id: str = "") -> None:
        self.warnings.append(
            {"code": code, "message": message, "element_id": element_id}
        )

    def _warn_unknown(self, element: Any, local: str) -> None:
        element_id = _clean_ref(element.get("id"))
        if element_id:
            self._warn(
                "UNKNOWN_ELEMENT",
                f"BPMN element '{local}' with ID '{element_id}' is not supported",
                element_id,
            )

    def _register_id(self, element_id: str, kind: str) -> None:
        previous = self._seen_ids.get(element_id)
        if previous is not None:
            raise BpmnParseError(f"Duplicate ID '{element_id}' ({previous} and {kind})")
        self._seen_ids[element_id] = kind

    def _parse_process(self, element: Any) -> None:
        process_id = _clean_ref(element.get("id"))
        name = _normalize_text(element.get("name"))

        if process_id:
            self._register_id(process_id, "process")
        else:
            self._warn("MISSING_ID", "Process has no ID")

        self.processes.append({"id": process_id, "name": name})
        self._parse_lane_sets(element, process_id)
        self._parse_flow_elements(element, process_id, process_id)

    def _parse_collaboration(self, element: Any) -> None:
        collaboration_id = _clean_ref(element.get("id"))
        if collaboration_id:
            self._register_id(collaboration_id, "collaboration")

        for child in _bpmn_children(element):
            local = _local_name(child.tag)
            if local == "participant":
                self._parse_participant(child)
            elif local == "messageFlow":
                self._parse_message_flow(child, collaboration_id)
            elif local in _IGNORED_COLLABORATION_ELEMENTS:
                continue
            else:
                self._warn_unknown(child, local)

    def _parse_participant(self, element: Any) -> None:
        participant_id = _clean_ref(element.get("id"))
        if not participant_id:
            self._warn("MISSING_ID", "Participant has no ID")
            return

        self._register_id(participant_id, "participant")
        self.participants.append(
            {
                "id": participant_id,
                "name": _normalize_text(element.get("name")),
                "process_ref": _clean_ref(element.get("processRef")),
            }
        )

    def _parse_lane_sets(self, element: Any, process_id: str) -> None:
        for child in _bpmn_children(element):
            if _local_name(child.tag) != "laneSet":
                continue
            for lane in _bpmn_children(child):
                if _local_name(lane.tag) == "lane":
                    self._parse_lane(lane, process_id, "")

    def _parse_lane(self, element: Any, process_id: str, parent_lane: str) -> None:
        lane_id = _clean_ref(element.get("id"))
        if not lane_id:
            self._warn("MISSING_ID", "Lane has no ID")
            self._parse_child_lanes(element, process_id, "")
            return

        self._register_id(lane_id, "lane")
        name = _normalize_text(element.get("name")) or lane_id
        self.lanes[lane_id] = {
            "id": lane_id,
            "name": name,
            "parent_lane": parent_lane,
            "process": process_id,
        }

        refs: list[str] = []
        self._lane_refs.append((lane_id, refs))
        for child in _bpmn_children(element):
            local = _local_name(child.tag)
            if local == "flowNodeRef":
                node_id = _clean_ref("".join(child.itertext()))
                if node_id:
                    refs.append(node_id)
            elif local == "childLaneSet":
                for lane in _bpmn_children(child):
                    if _local_name(lane.tag) == "lane":
                        self._parse_lane(lane, process_id, lane_id)

    def _parse_child_lanes(
        self, element: Any, process_id: str, parent_lane: str
    ) -> None:
        for child in _bpmn_children(element):
            if _local_name(child.tag) != "childLaneSet":
                continue
            for lane in _bpmn_children(child):
                if _local_name(lane.tag) == "lane":
                    self._parse_lane(lane, process_id, parent_lane)

    def _parse_flow_elements(
        self, parent: Any, process_id: str, parent_id: str
    ) -> None:
        for child in _bpmn_children(parent):
            local = _local_name(child.tag)
            if local in NODE_TYPES:
                node_id = self._parse_node(child, process_id, parent_id)
                if local == "subProcess":
                    self._parse_lane_sets(child, process_id)
                    self._parse_flow_elements(child, process_id, node_id)
            elif local == "sequenceFlow":
                self._parse_sequence_flow(child, process_id, parent_id)
            elif local in _IGNORED_FLOW_ELEMENTS:
                continue
            else:
                self._warn_unknown(child, local)

    def _parse_node(self, element: Any, process_id: str, parent_id: str) -> str:
        local = _local_name(element.tag)
        node_id = _clean_ref(element.get("id"))
        if not node_id:
            self._warn("MISSING_ID", f"Node '{local}' has no ID")
            return ""

        self._register_id(node_id, "node")
        self.nodes[node_id] = {
            "id": node_id,
            "type": local,
            "name": _normalize_text(element.get("name")),
            "lane": "",
            "lane_id": "",
            "lane_path": [],
            "parent": parent_id,
            "process": process_id,
            "documentation": self._documentation(element),
            "default_flow": _clean_ref(element.get("default")),
            "gateway_direction": (
                _normalize_text(element.get("gatewayDirection"))
                if local.endswith("Gateway")
                else ""
            ),
            "event_definition": self._event_definition(element),
            "loop": self._loop(element),
            "called_element": (
                _clean_ref(element.get("calledElement"))
                if local == "callActivity"
                else ""
            ),
            "attached_to": (
                _clean_ref(element.get("attachedToRef"))
                if local == "boundaryEvent"
                else ""
            ),
            "cancel_activity": (
                _clean_ref(element.get("cancelActivity"))
                if local == "boundaryEvent"
                else ""
            ),
        }
        return node_id

    def _documentation(self, element: Any) -> str:
        parts = [
            _normalize_text("".join(child.itertext()))
            for child in _bpmn_children(element)
            if _local_name(child.tag) == "documentation"
        ]
        return " ".join(part for part in parts if part)

    def _event_definition(self, element: Any) -> str:
        names: list[str] = []
        for child in _bpmn_children(element):
            local = _local_name(child.tag)
            if not local.endswith(_EVENT_DEFINITION_SUFFIX):
                continue
            name = local[: -len(_EVENT_DEFINITION_SUFFIX)].lower()
            names.append(_EVENT_DEFINITION_ALIASES.get(name, name))

        if not names:
            return ""
        if len(names) > 1:
            return "multiple"
        return names[0]

    def _loop(self, element: Any) -> str:
        for child in _bpmn_children(element):
            local = _local_name(child.tag)
            if local == "standardLoopCharacteristics":
                return "standard"
            if local == "multiInstanceLoopCharacteristics":
                sequential = (
                    _normalize_text(child.get("isSequential")).lower() == "true"
                )
                return (
                    "multi_instance_sequential"
                    if sequential
                    else "multi_instance_parallel"
                )
        return ""

    def _parse_sequence_flow(
        self, element: Any, process_id: str, parent_id: str
    ) -> None:
        flow_id = _clean_ref(element.get("id"))
        if not flow_id:
            self._warn("MISSING_ID", "sequenceFlow has no ID")
            return

        self._register_id(flow_id, "flow")
        source = _clean_ref(element.get("sourceRef"))
        target = _clean_ref(element.get("targetRef"))
        if not source or not target:
            self._warn(
                "MISSING_ENDPOINT",
                f"sequenceFlow '{flow_id}' has no sourceRef or targetRef",
                flow_id,
            )
            return

        self.flows[flow_id] = {
            "id": flow_id,
            "type": "sequence",
            "source": source,
            "target": target,
            "name": _normalize_text(element.get("name")),
            "condition": self._condition(element),
            "parent": parent_id,
            "process": process_id,
        }

    def _parse_message_flow(self, element: Any, collaboration_id: str) -> None:
        flow_id = _clean_ref(element.get("id"))
        if not flow_id:
            self._warn("MISSING_ID", "messageFlow has no ID")
            return

        self._register_id(flow_id, "flow")
        source = _clean_ref(element.get("sourceRef"))
        target = _clean_ref(element.get("targetRef"))
        if not source or not target:
            self._warn(
                "MISSING_ENDPOINT",
                f"messageFlow '{flow_id}' has no sourceRef or targetRef",
                flow_id,
            )
            return

        self.flows[flow_id] = {
            "id": flow_id,
            "type": "message",
            "source": source,
            "target": target,
            "name": _normalize_text(element.get("name")),
            "condition": self._condition(element),
            "parent": collaboration_id,
            "process": "",
        }

    def _condition(self, element: Any) -> str:
        for child in _bpmn_children(element):
            if _local_name(child.tag) == "conditionExpression":
                return _normalize_text("".join(child.itertext()))
        return ""

    def _assign_lanes(self) -> None:
        assignments: dict[str, str] = {}
        for lane_id, refs in self._lane_refs:
            for node_id in refs:
                if node_id not in self.nodes:
                    continue
                current = assignments.get(node_id)
                if current is None:
                    assignments[node_id] = lane_id
                elif current != lane_id:
                    self._warn(
                        "MULTI_LANE",
                        f"Node '{node_id}' is assigned to lanes '{current}' and "
                        f"'{lane_id}'; using the first lane, '{current}'",
                        node_id,
                    )

        for node_id, node in self.nodes.items():
            lane_id = assignments.get(node_id, "")
            if not lane_id:
                continue
            lane = self.lanes[lane_id]
            node["lane_id"] = lane_id
            node["lane"] = lane["name"]
            node["lane_path"] = self._lane_path(lane_id)

    def _lane_path(self, lane_id: str) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        current = lane_id
        while current and current not in seen:
            seen.add(current)
            lane = self.lanes.get(current)
            if lane is None:
                break
            names.append(lane["name"])
            current = lane["parent_lane"]
        names.reverse()
        return names

    def _check_dangling_references(self) -> None:
        participant_ids = {participant["id"] for participant in self.participants}

        for flow_id, flow in self.flows.items():
            valid_targets = self.nodes
            if flow["type"] == "message":
                valid_targets = self.nodes.keys() | participant_ids
            for endpoint in ("source", "target"):
                reference = flow[endpoint]
                if reference not in valid_targets:
                    self._warn(
                        "DANGLING_REF",
                        f"Flow '{flow_id}' references non-existent element '{reference}'",
                        flow_id,
                    )

        for node_id, node in self.nodes.items():
            default_flow = node["default_flow"]
            if default_flow and default_flow not in self.flows:
                self._warn(
                    "DANGLING_REF",
                    f"Node '{node_id}' uses non-existent default flow '{default_flow}'",
                    node_id,
                )

            attached_to = node["attached_to"]
            if attached_to and attached_to not in self.nodes:
                self._warn(
                    "DANGLING_REF",
                    f"Boundary event '{node_id}' is attached to non-existent node "
                    f"'{attached_to}'",
                    node_id,
                )


def _force_utf8(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        pass


def _file_summary(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_file": model["source_file"],
        "processes": len(model["processes"]),
        "participants": len(model["participants"]),
        "lanes": len(model["lanes"]),
        "nodes": len(model["nodes"]),
        "flows": len(model["flows"]),
        "warnings": model["warnings"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m core.bpmn_parser",
        description="Show a summary of one or more BPMN 2.0 files.",
    )
    parser.add_argument("files", nargs="+", type=Path, help="BPMN file")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat all warnings as errors",
    )
    args = parser.parse_args(argv)

    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)

    summaries: list[dict[str, Any]] = []
    try:
        for file_path in args.files:
            model = parse_bpmn(file_path, strict=args.strict)
            summaries.append(_file_summary(model))
    except BpmnParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    payload = {"schema_version": SCHEMA_VERSION, "files": summaries}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
