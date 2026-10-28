from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.bpmn_parser import (
    BPMN_NAMESPACE,
    MAX_FILE_SIZE,
    NODE_TYPES,
    SCHEMA_VERSION,
    BpmnParseError,
    parse_bpmn,
    parse_bpmn_string,
)

FIXTURES = Path(__file__).parent / "fixtures"


def wrap(body: str, *, extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<definitions xmlns="{BPMN_NAMESPACE}" '
        'xmlns:camunda="http://camunda.org/schema/1.0/bpmn" '
        'id="Definitions_Test" targetNamespace="http://example.com/bpmn">\n'
        '  <process id="P" name="Proses">\n'
        f"{body}\n"
        "  </process>\n"
        f"{extra}\n"
        "</definitions>\n"
    )


def warning_codes(model: dict) -> list[str]:
    return [warning["code"] for warning in model["warnings"]]


def test_parse_basic_fixture() -> None:
    path = FIXTURES / "basic_old.bpmn"
    model = parse_bpmn(path)

    assert model["schema_version"] == SCHEMA_VERSION
    assert model["source_file"] == str(path)
    assert model["processes"] == [{"id": "P2P", "name": "Procure to Pay"}]
    assert model["lanes"] == {
        "LANE-PUR": {
            "id": "LANE-PUR",
            "name": "Purchasing",
            "parent_lane": "",
            "process": "P2P",
        }
    }

    node = model["nodes"]["S00"]
    assert node["type"] == "subProcess"
    assert node["name"] == "Verifikasi Dokumen"
    assert node["lane"] == "Purchasing"
    assert node["lane_id"] == "LANE-PUR"
    assert node["lane_path"] == ["Purchasing"]
    assert node["parent"] == "P2P"
    assert node["process"] == "P2P"
    assert node["documentation"] == "Dokumen diperiksa"

    flow = model["flows"]["F1"]
    assert flow == {
        "id": "F1",
        "type": "sequence",
        "source": "START",
        "target": "S00",
        "name": "",
        "condition": "",
        "parent": "P2P",
        "process": "P2P",
    }
    assert model["warnings"] == []


def test_parse_bpmn_accepts_str_and_path() -> None:
    path = FIXTURES / "basic_old.bpmn"
    from_path = parse_bpmn(path)
    from_str = parse_bpmn(str(path))
    assert from_path == from_str


def test_parse_bpmn_string_matches_file() -> None:
    path = FIXTURES / "basic_old.bpmn"
    from_file = parse_bpmn(path)
    from_string = parse_bpmn_string(path.read_text(encoding="utf-8"))
    from_file.pop("source_file")
    assert from_string.pop("source_file") == ""
    assert from_string == from_file


def test_namespace_prefix_independent() -> None:
    default_ns = (
        f'<definitions xmlns="{BPMN_NAMESPACE}" id="D">'
        '<process id="P" name="Proses"><task id="T" name="Tugas"/></process>'
        "</definitions>"
    )
    prefixed = (
        f'<bpmn2:definitions xmlns:bpmn2="{BPMN_NAMESPACE}" id="D">'
        '<bpmn2:process id="P" name="Proses">'
        '<bpmn2:task id="T" name="Tugas"/>'
        "</bpmn2:process></bpmn2:definitions>"
    )

    first = parse_bpmn_string(default_ns)
    second = parse_bpmn_string(prefixed)
    assert first["nodes"] == second["nodes"]
    assert first["processes"] == second["processes"]


def test_all_supported_node_types() -> None:
    body = "\n".join(
        f'<{node_type} id="N_{node_type}"'
        + (' attachedToRef="N_task"' if node_type == "boundaryEvent" else "")
        + "/>"
        for node_type in sorted(NODE_TYPES)
    )
    model = parse_bpmn_string(wrap(body))
    assert set(model["nodes"]) == {f"N_{node_type}" for node_type in NODE_TYPES}
    assert {node["type"] for node in model["nodes"].values()} == set(NODE_TYPES)
    assert model["nodes"]["N_task"]["name"] == ""
    assert model["warnings"] == []


def test_node_special_fields() -> None:
    body = """
    <task id="T" name="Tugas" default="F1">
      <documentation>  Dokumen  penting </documentation>
    </task>
    <exclusiveGateway id="GW" gatewayDirection="Diverging" default="F1"/>
    <startEvent id="EVT_MESSAGE">
      <messageEventDefinition/>
    </startEvent>
    <intermediateCatchEvent id="EVT_MULTIPLE">
      <timerEventDefinition/>
      <signalEventDefinition/>
    </intermediateCatchEvent>
    <endEvent id="EVT_COMPENSATION">
      <compensateEventDefinition/>
    </endEvent>
    <userTask id="LOOP_STANDARD">
      <standardLoopCharacteristics/>
    </userTask>
    <userTask id="LOOP_SEQUENTIAL">
      <multiInstanceLoopCharacteristics isSequential="true"/>
    </userTask>
    <userTask id="LOOP_PARALLEL">
      <multiInstanceLoopCharacteristics/>
    </userTask>
    <callActivity id="CALL" calledElement="PROC-2"/>
    <boundaryEvent id="BND" attachedToRef="T" cancelActivity="false"/>
    <sequenceFlow id="F1" sourceRef="T" targetRef="GW"/>
    """
    nodes = parse_bpmn_string(wrap(body))["nodes"]

    assert nodes["T"]["documentation"] == "Dokumen penting"
    assert nodes["T"]["default_flow"] == "F1"
    assert nodes["GW"]["gateway_direction"] == "Diverging"
    assert nodes["EVT_MESSAGE"]["event_definition"] == "message"
    assert nodes["EVT_MULTIPLE"]["event_definition"] == "multiple"
    assert nodes["EVT_COMPENSATION"]["event_definition"] == "compensation"
    assert nodes["LOOP_STANDARD"]["loop"] == "standard"
    assert nodes["LOOP_SEQUENTIAL"]["loop"] == "multi_instance_sequential"
    assert nodes["LOOP_PARALLEL"]["loop"] == "multi_instance_parallel"
    assert nodes["CALL"]["called_element"] == "PROC-2"
    assert nodes["BND"]["attached_to"] == "T"
    assert nodes["BND"]["cancel_activity"] == "false"


def test_nested_subprocess_and_multiple_processes() -> None:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <definitions xmlns="{BPMN_NAMESPACE}" id="D">
      <process id="P1" name="Satu">
        <subProcess id="SUB" name="Sub">
          <userTask id="T1" name="Dalam"/>
          <sequenceFlow id="F1" sourceRef="T1" targetRef="T1"/>
        </subProcess>
      </process>
      <process id="P2" name="Dua">
        <task id="T2" name="Luar"/>
        <sequenceFlow id="F2" sourceRef="T2" targetRef="T2"/>
      </process>
    </definitions>
    """
    model = parse_bpmn_string(xml)

    assert model["processes"] == [
        {"id": "P1", "name": "Satu"},
        {"id": "P2", "name": "Dua"},
    ]
    assert model["nodes"]["SUB"]["parent"] == "P1"
    assert model["nodes"]["T1"]["parent"] == "SUB"
    assert model["nodes"]["T1"]["process"] == "P1"
    assert model["nodes"]["T2"]["parent"] == "P2"
    assert model["flows"]["F1"]["parent"] == "SUB"
    assert model["flows"]["F1"]["process"] == "P1"
    assert model["flows"]["F2"]["parent"] == "P2"


def test_nested_lanes_and_unnamed_lane() -> None:
    body = """
    <laneSet>
      <lane id="L1" name="Divisi">
        <childLaneSet>
          <lane id="L1A">
            <flowNodeRef>T1</flowNodeRef>
          </lane>
        </childLaneSet>
      </lane>
    </laneSet>
    <task id="T1"/>
    <task id="T2"/>
    """
    model = parse_bpmn_string(wrap(body))

    assert model["lanes"]["L1A"]["name"] == "L1A"
    assert model["lanes"]["L1A"]["parent_lane"] == "L1"
    assert model["nodes"]["T1"]["lane"] == "L1A"
    assert model["nodes"]["T1"]["lane_path"] == ["Divisi", "L1A"]
    assert model["nodes"]["T2"]["lane"] == ""
    assert model["nodes"]["T2"]["lane_id"] == ""
    assert model["nodes"]["T2"]["lane_path"] == []


def test_multi_lane_warning_uses_first_lane() -> None:
    body = """
    <laneSet>
      <lane id="L1" name="Pertama"><flowNodeRef>T</flowNodeRef></lane>
      <lane id="L2" name="Kedua"><flowNodeRef>T</flowNodeRef></lane>
    </laneSet>
    <task id="T"/>
    """
    model = parse_bpmn_string(wrap(body))

    assert model["nodes"]["T"]["lane_id"] == "L1"
    assert model["nodes"]["T"]["lane"] == "Pertama"
    assert warning_codes(model) == ["MULTI_LANE"]
    assert model["warnings"][0]["element_id"] == "T"


def test_missing_id_endpoint_and_unknown_element() -> None:
    body = """
    <task name="Tanpa ID"/>
    <sequenceFlow id="F"/>
    <dataObject id="D1"/>
    """
    model = parse_bpmn_string(wrap(body))

    assert model["nodes"] == {}
    assert model["flows"] == {}
    assert set(warning_codes(model)) == {
        "MISSING_ID",
        "MISSING_ENDPOINT",
        "UNKNOWN_ELEMENT",
    }


def test_unknown_definitions_and_collaboration_elements() -> None:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <definitions xmlns="{BPMN_NAMESPACE}" id="D">
      <message id="MSG1"/>
      <process id="P"><task id="T"/></process>
      <collaboration id="C"><conversation id="CONV1"/></collaboration>
    </definitions>
    """
    model = parse_bpmn_string(xml)

    assert warning_codes(model) == ["UNKNOWN_ELEMENT", "UNKNOWN_ELEMENT"]
    assert {warning["element_id"] for warning in model["warnings"]} == {"MSG1", "CONV1"}


def test_dangling_references() -> None:
    body = """
    <task id="T" default="F9"/>
    <boundaryEvent id="B" attachedToRef="X"/>
    <sequenceFlow id="F" sourceRef="T" targetRef="Y"/>
    """
    model = parse_bpmn_string(wrap(body))

    dangling = [
        warning for warning in model["warnings"] if warning["code"] == "DANGLING_REF"
    ]
    assert {warning["element_id"] for warning in dangling} == {"F", "T", "B"}


def test_duplicate_id_across_element_kinds() -> None:
    body = """
    <laneSet>
      <lane id="X" name="Lane"><flowNodeRef>T</flowNodeRef></lane>
    </laneSet>
    <task id="T"/>
    <task id="X"/>
    """
    with pytest.raises(BpmnParseError, match="X"):
        parse_bpmn_string(wrap(body))


def test_strict_mode_promotes_warnings() -> None:
    body = '<task name="Tanpa ID"/>'
    model = parse_bpmn_string(wrap(body))
    assert warning_codes(model) == ["MISSING_ID"]

    with pytest.raises(BpmnParseError, match="strict"):
        parse_bpmn_string(wrap(body), strict=True)


def test_text_normalization_and_id_case() -> None:
    body = """
    <task id="T1" name="Cafe\u0301  Baru
      Sekali"/>
    <task id="ID_Kecil" name="Nama Kecil"/>
    <task id="ID_kecil" name="Nama kecil"/>
    <userTask id="T2">
      <documentation>  Dokumen
        penting  </documentation>
    </userTask>
    <sequenceFlow id="F1" sourceRef="T1" targetRef="T2">
      <conditionExpression>  x
        &gt;  0 </conditionExpression>
    </sequenceFlow>
    """
    model = parse_bpmn_string(wrap(body))

    assert model["nodes"]["T1"]["name"] == "Café Baru Sekali"
    assert model["nodes"]["T2"]["documentation"] == "Dokumen penting"
    assert model["flows"]["F1"]["condition"] == "x > 0"
    assert "ID_Kecil" in model["nodes"]
    assert "ID_kecil" in model["nodes"]


def test_parse_bpmn_string_with_encoding_declaration() -> None:
    xml = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>\n'
        f'<definitions xmlns="{BPMN_NAMESPACE}">'
        '<process id="P"><task id="T" name="Café"/></process>'
        "</definitions>"
    )
    model = parse_bpmn_string(xml)
    assert model["nodes"]["T"]["name"] == "Café"


def test_encoding_bom_utf8(tmp_path: Path) -> None:
    xml = wrap('<task id="T" name="Café"/>')
    path = tmp_path / "bom.bpmn"
    path.write_bytes(b"\xef\xbb\xbf" + xml.encode("utf-8"))
    assert parse_bpmn(path)["nodes"]["T"]["name"] == "Café"


def test_encoding_utf16(tmp_path: Path) -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        f'<definitions xmlns="{BPMN_NAMESPACE}">'
        '<process id="P"><task id="T" name="Café"/></process>'
        "</definitions>"
    )
    path = tmp_path / "utf16.bpmn"
    path.write_bytes(xml.encode("utf-16"))
    assert parse_bpmn(path)["nodes"]["T"]["name"] == "Café"


def test_encoding_iso_8859_1_and_space_in_path(tmp_path: Path) -> None:
    xml = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        f'<definitions xmlns="{BPMN_NAMESPACE}">'
        '<process id="P"><task id="T" name="Café"/></process>'
        "</definitions>"
    )
    path = tmp_path / "file dengan spasi.bpmn"
    path.write_bytes(xml.encode("iso-8859-1"))
    assert parse_bpmn(path)["nodes"]["T"]["name"] == "Café"


def test_file_too_large(tmp_path: Path) -> None:
    path = tmp_path / "besar.bpmn"
    with path.open("wb") as handle:
        handle.truncate(MAX_FILE_SIZE + 1)

    with pytest.raises(BpmnParseError, match="20 MB"):
        parse_bpmn(path)


def test_xml_security_blocks_dtd_and_entities() -> None:
    xxe = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE definitions [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        f'<definitions xmlns="{BPMN_NAMESPACE}">'
        '<process id="P"><task id="T" name="&xxe;"/></process>'
        "</definitions>"
    )
    billion_laughs = (
        '<?xml version="1.0"?>'
        "<!DOCTYPE definitions ["
        '<!ENTITY lol "lol">'
        '<!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        '<!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">'
        "]>"
        f'<definitions xmlns="{BPMN_NAMESPACE}">'
        '<process id="P"><task id="T" name="&lol2;"/></process>'
        "</definitions>"
    )

    with pytest.raises(BpmnParseError):
        parse_bpmn_string(xxe)
    with pytest.raises(BpmnParseError):
        parse_bpmn_string(billion_laughs)


def test_malformed_xml_reports_line(tmp_path: Path) -> None:
    path = tmp_path / "rusak.bpmn"
    path.write_text(
        f'<definitions xmlns="{BPMN_NAMESPACE}"><process id="P">',
        encoding="utf-8",
    )
    with pytest.raises(BpmnParseError, match="baris"):
        parse_bpmn(path)


def test_invalid_root_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(BpmnParseError, match="definitions"):
        parse_bpmn_string(f'<bukan xmlns="{BPMN_NAMESPACE}"/>')

    missing = tmp_path / "tidak-ada.bpmn"
    with pytest.raises(BpmnParseError, match=str(missing)):
        parse_bpmn(missing)


def test_vendor_extensions_are_ignored() -> None:
    body = """
    <task id="T" name="Tugas" camunda:assignee="budi">
      <extensionElements>
        <camunda:inputOutput>
          <camunda:inputParameter name="x">1</camunda:inputParameter>
        </camunda:inputOutput>
      </extensionElements>
    </task>
    """
    model = parse_bpmn_string(wrap(body))
    assert model["nodes"]["T"]["name"] == "Tugas"
    assert model["warnings"] == []


def test_participants_and_message_flow() -> None:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <definitions xmlns="{BPMN_NAMESPACE}" id="D">
      <process id="P1" name="Satu"><task id="T1"/></process>
      <process id="P2" name="Dua"><task id="T2"/></process>
      <collaboration id="C1">
        <participant id="PART1" name="Pool A" processRef="P1"/>
        <participant id="PART2" name="Pool B" processRef="P2"/>
        <messageFlow id="MF1" name="Pesan" sourceRef="T1" targetRef="T2"/>
      </collaboration>
    </definitions>
    """
    model = parse_bpmn_string(xml)

    assert model["participants"] == [
        {"id": "PART1", "name": "Pool A", "process_ref": "P1"},
        {"id": "PART2", "name": "Pool B", "process_ref": "P2"},
    ]
    assert model["flows"]["MF1"] == {
        "id": "MF1",
        "type": "message",
        "source": "T1",
        "target": "T2",
        "name": "Pesan",
        "condition": "",
        "parent": "C1",
        "process": "",
    }
    assert model["warnings"] == []


def test_model_is_json_serializable() -> None:
    model = parse_bpmn(FIXTURES / "basic_old.bpmn")
    assert json.loads(json.dumps(model, ensure_ascii=False)) == model
