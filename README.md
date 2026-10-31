# BPMN Parser and Diff

A Python tool for reading BPMN 2.0 files and comparing two versions of a business process diagram. This project is a component of **Code Change Planning from BPMN Changes** (Group 7, Enterprise Systems, ITS).

## Purpose

- The **Parser** converts a single `.bpmn` file into a compact data model containing processes, participants, lanes, nodes, flows, and leveled warnings (`info`/`warning`).
- The **Diff** compares the old and new models and produces a structured list of changes: nodes/flows added, removed, or changed (`retyped`, `renamed`, `lane_moved`, `event_detail_changed`, `loop_detail_changed`, `rewired_source`, and so on), including changes to lanes, processes, and participants.
- The diff result is used as shared input by the A/B/C experiment setups, scenario generators, and evaluators, so it must be **deterministic, repeatable, and versioned** (`schema_version` is currently `1.1`).
- It does not use an LLM, does not access the network, and ignores diagram layout (the DI section).

The output contract and the behavior of each function are described in detail in [`core/README.md`](core/README.md).

## Project Structure

```
core/               # parser and diff implementation
  bpmn_parser.py    # BPMN parser -> model
  bpmn_diff.py      # diff of two models + CLI
  constants.py      # warning codes, levels, label kinds, schema version
  schema.py         # TypedDict for the model and diff result shapes
  _cli.py           # shared helpers (UTF-8, POSIX paths)
bpmn/               # sample BPMN files (old/new)
output/             # automatic diff results (empty except for .gitkeep)
```

## Prerequisites

- Python 3.10 or newer
- Dependency: `defusedxml` (see `requirements.txt`)

## How to Run

### 1. Set up a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 2. Parse one or more BPMN files

```bash
python -m core.bpmn_parser bpmn/new/p2p_test_new.bpmn
```

The output is a JSON summary (the number of processes, participants, lanes, nodes, flows, and warnings). Parser options:

| Option | Description |
|---|---|
| `--strict` | Treats `warning`-level warnings as errors; `info` does not block |
| `--types` | Adds per-BPMN-type node counts |
| `--debug` | Prints a traceback for unexpected errors |
| `--version` | Prints the output schema version |

### 3. Compare two BPMN versions

```bash
python -m core.bpmn_diff bpmn/old/p2p_test_old.bpmn bpmn/new/p2p_test_new.bpmn --json
```

Available options:

| Option | Description |
|---|---|
| `--md` | Saves the result as Markdown |
| `--json` | Saves the result as JSON |
| `--strict` | Treats `warning`-level warnings as errors; `info` does not block |
| `--debug` | Prints a traceback for unexpected errors |
| `--version` | Prints the output schema version |

The result is always saved as a file in `output/` with a timestamped name, for example `output/20261030_165744_374649.json` or `.md`. Stdout only shows the path of the result file.

Examples:

```bash
python -m core.bpmn_diff bpmn/old/p2p_test_old.bpmn \
  bpmn/new/p2p_test_new.bpmn --json

python -m core.bpmn_diff bpmn/old/p2p_test_old.bpmn \
  bpmn/new/p2p_test_new.bpmn --md
```

Exit codes: `0` success, `2` a file failed to be read/parsed or a `--strict` violation, `1` another error.

### 4. Use as a library

```python
from core.bpmn_parser import parse_bpmn
from core.bpmn_diff import diff_files, get_context

old = parse_bpmn("bpmn/old/p2p_test_old.bpmn")
new = parse_bpmn("bpmn/new/p2p_test_new.bpmn")
result = diff_files("bpmn/old/p2p_test_old.bpmn", "bpmn/new/p2p_test_new.bpmn")

ctx = get_context(new, "TASK-ID")
```

## Output Format

The diff returns a JSON dict with the keys `schema_version`, `old_file`, `new_file`, `summary`, `nodes`, `flows`, `lanes`, `processes`, `participants`, and `warnings`. Participants are separated from processes; `summary` also contains a `kinds` histogram, a list of `touched_node_ids`, and a count of `warnings`. All lists are sorted by ID so the result is stable regardless of XML order.

Each warning contains a `level` (`info` or `warning`). The parser marks data/definition elements as `info`, while data loss or inconsistent references are marked as `warning`.
