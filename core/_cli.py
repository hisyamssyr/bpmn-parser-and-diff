from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "BPMN_DIR",
    "BpmnPathError",
    "NEW_BPMN_DIR",
    "OLD_BPMN_DIR",
    "display_path",
    "force_utf8",
    "resolve_bpmn_file",
]

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
BPMN_DIR = _PROJECT_ROOT / "bpmn"
OLD_BPMN_DIR = BPMN_DIR / "old"
NEW_BPMN_DIR = BPMN_DIR / "new"

_SIDE_DIRS = {"old": OLD_BPMN_DIR, "new": NEW_BPMN_DIR}


class BpmnPathError(Exception):
    pass


def force_utf8(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8")
    except (OSError, ValueError):
        pass


def display_path(value: str | Path) -> str:
    text = str(value)
    if not text:
        return ""
    return Path(text.replace("\\", "/")).as_posix()


def _project_relative(path: Path) -> Path:
    try:
        return path.relative_to(_PROJECT_ROOT)
    except ValueError:
        return path


def resolve_bpmn_file(name: str | Path, side: str | None = None) -> Path:
    path = Path(name)

    if path.is_absolute():
        return path

    parts = path.parts
    if len(parts) > 1:
        if parts[0] == "bpmn":
            return path
        if parts[0] in _SIDE_DIRS and len(parts) == 2:
            return Path("bpmn") / path
        return path

    directories = (_SIDE_DIRS[side],) if side else (OLD_BPMN_DIR, NEW_BPMN_DIR)
    matches = [directory / path.name for directory in directories]
    found = [candidate for candidate in matches if candidate.is_file()]

    if len(found) == 1:
        return _project_relative(found[0])
    if len(found) > 1:
        raise BpmnPathError(
            f"BPMN file '{path.name}' exists in both bpmn/old and bpmn/new; "
            "use 'old/<name>' or 'new/<name>'"
        )

    searched = ", ".join(display_path(candidate) for candidate in matches)
    raise BpmnPathError(
        f"BPMN file '{path.name}' not found (looked in {searched})"
    )
