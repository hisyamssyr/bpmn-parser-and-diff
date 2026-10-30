from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["display_path", "force_utf8"]


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
