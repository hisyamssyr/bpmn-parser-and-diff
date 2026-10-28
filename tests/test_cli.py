from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from core.bpmn_parser import BPMN_NAMESPACE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def run_module(
    module: str,
    *args: object,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", module, *(str(arg) for arg in args)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        env=merged_env,
        check=False,
    )


def process_xml(body: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<definitions xmlns="{BPMN_NAMESPACE}" id="D">'
        f'<process id="P" name="Proses">{body}</process>'
        "</definitions>"
    )


def write_xml(path: Path, body: str) -> Path:
    path.write_text(process_xml(body), encoding="utf-8")
    return path


def test_diff_cli_json() -> None:
    result = run_module(
        "core.bpmn_diff",
        FIXTURES / "basic_old.bpmn",
        FIXTURES / "basic_new.bpmn",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["summary"]["nodes"]["changed"] == 1


def test_diff_cli_markdown() -> None:
    result = run_module(
        "core.bpmn_diff",
        FIXTURES / "basic_old.bpmn",
        FIXTURES / "basic_new.bpmn",
        "--md",
    )

    assert result.returncode == 0
    text = result.stdout.decode("utf-8")
    assert text.startswith("# BPMN Diff")
    assert "## Node" in text
    assert "`S00`: retyped" in text


def test_diff_cli_out_writes_utf8_file(tmp_path: Path) -> None:
    old = write_xml(tmp_path / "old.bpmn", '<task id="T" name="Café"/>')
    new = write_xml(tmp_path / "new.bpmn", '<task id="T" name="Café Baru"/>')
    output = tmp_path / "hasil.json"

    result = run_module("core.bpmn_diff", old, new, "--out", output)

    assert result.returncode == 0
    assert result.stdout == b""
    content = output.read_bytes()
    assert "Café".encode() in content
    assert json.loads(content.decode("utf-8"))["summary"]["nodes"]["changed"] == 1


def test_diff_cli_markdown_out(tmp_path: Path) -> None:
    old = write_xml(tmp_path / "old.bpmn", '<task id="T" name="A"/>')
    new = write_xml(tmp_path / "new.bpmn", '<task id="T" name="B"/>')
    output = tmp_path / "hasil.md"

    result = run_module("core.bpmn_diff", old, new, "--md", "--out", output)

    assert result.returncode == 0
    assert output.read_text(encoding="utf-8").startswith("# BPMN Diff")


def test_diff_cli_strict_warning_exit_2(tmp_path: Path) -> None:
    old = write_xml(
        tmp_path / "old.bpmn",
        '<task id="T"/><sequenceFlow id="F" sourceRef="T" targetRef="X"/>',
    )
    new = write_xml(tmp_path / "new.bpmn", '<task id="T"/>')

    non_strict = run_module("core.bpmn_diff", old, new)
    assert non_strict.returncode == 0
    warnings = json.loads(non_strict.stdout.decode("utf-8"))["warnings"]
    assert warnings[0]["code"] == "DANGLING_REF"
    assert warnings[0]["side"] == "old"

    strict = run_module("core.bpmn_diff", old, new, "--strict")
    assert strict.returncode == 2
    assert b"Error" in strict.stderr


def test_diff_cli_missing_file_exit_2(tmp_path: Path) -> None:
    result = run_module(
        "core.bpmn_diff",
        tmp_path / "tidak-ada.bpmn",
        FIXTURES / "basic_new.bpmn",
    )
    assert result.returncode == 2
    assert b"Error" in result.stderr


def test_diff_cli_write_error_exit_1(tmp_path: Path) -> None:
    result = run_module(
        "core.bpmn_diff",
        FIXTURES / "basic_old.bpmn",
        FIXTURES / "basic_new.bpmn",
        "--out",
        tmp_path / "tidak-ada" / "hasil.json",
    )
    assert result.returncode == 1
    assert b"unable to write" in result.stderr


def test_diff_cli_deterministic_with_hash_seed() -> None:
    first = run_module(
        "core.bpmn_diff",
        FIXTURES / "lanes_old.bpmn",
        FIXTURES / "lanes_new.bpmn",
        env={"PYTHONHASHSEED": "1"},
    )
    second = run_module(
        "core.bpmn_diff",
        FIXTURES / "lanes_old.bpmn",
        FIXTURES / "lanes_new.bpmn",
        env={"PYTHONHASHSEED": "987"},
    )

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout


def test_parser_cli_multiple_files_utf8(tmp_path: Path) -> None:
    extra = write_xml(tmp_path / "café.bpmn", '<task id="T" name="Café"/>')
    result = run_module(
        "core.bpmn_parser",
        FIXTURES / "basic_old.bpmn",
        extra,
    )

    assert result.returncode == 0
    assert "café".encode() in result.stdout
    payload = json.loads(result.stdout.decode("utf-8"))
    assert len(payload["files"]) == 2
    assert payload["files"][0]["nodes"] == 3
    assert payload["files"][1]["nodes"] == 1


def test_parser_cli_warning_and_strict(tmp_path: Path) -> None:
    warning = write_xml(tmp_path / "warning.bpmn", '<task name="Tanpa ID"/>')

    non_strict = run_module("core.bpmn_parser", warning)
    assert non_strict.returncode == 0
    payload = json.loads(non_strict.stdout.decode("utf-8"))
    assert payload["files"][0]["warnings"][0]["code"] == "MISSING_ID"

    strict = run_module("core.bpmn_parser", warning, "--strict")
    assert strict.returncode == 2
    assert b"Error" in strict.stderr


def test_parser_cli_malformed_exit_2(tmp_path: Path) -> None:
    broken = tmp_path / "rusak.bpmn"
    broken.write_text(
        f'<definitions xmlns="{BPMN_NAMESPACE}"><process id="P">',
        encoding="utf-8",
    )
    result = run_module("core.bpmn_parser", broken)
    assert result.returncode == 2
    assert b"Error" in result.stderr
