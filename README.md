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
core/               # parser, diff, and LLM view implementation
  bpmn_parser.py    # BPMN parser -> model (API only)
  bpmn_diff.py      # diff of two models + CLI
  llm_view.py       # compact LLM-friendly diff view + prompt block + CLI
  constants.py      # warning codes, levels, label kinds, schema version
  schema.py         # TypedDict for the model and diff result shapes
  _cli.py           # shared helpers (BPMN path resolution, UTF-8, POSIX paths)
bpmn/old/           # old BPMN files
bpmn/new/           # new BPMN files
tests/              # pytest tests and diff fixtures
output/diff/        # automatic diff results
output/view/        # automatic llm_view results
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

For development and tests:

```bash
pip install -r requirements-dev.txt
pytest
```

### 2. Compare two BPMN versions

Place the old file in `bpmn/old/` and the new file in `bpmn/new/`, then pass only their names:

```bash
python -m core.bpmn_diff p2p_test_old.bpmn p2p_test_new.bpmn --json
```

Both file names must be given in full.

Available options:

| Option | Description |
|---|---|
| `--md` | Saves the result as Markdown |
| `--json` | Saves the result as JSON |
| `--strict` | Treats `warning`-level warnings as errors; `info` does not block |
| `--debug` | Prints a traceback for unexpected errors |
| `--version` | Prints the output schema version |

The result is always saved as a file in `output/diff/` with a timestamped name, for example `output/diff/20261030_165744_374649.json` or `.md`. Stdout only shows the path of the result file.

Examples:

```bash
python -m core.bpmn_diff p2p_test_old.bpmn p2p_test_new.bpmn --json
python -m core.bpmn_diff p2p_test_old.bpmn p2p_test_new.bpmn --md
```

Exit codes: `0` success, `2` a file failed to be read/parsed or a `--strict` violation, `1` another error.

### 3. Build a compact LLM view

`llm_view` turns a saved diff into a deterministic, compact JSON/plain-text
representation with element names and reading rules, plus a ready-to-paste
prompt block.

```bash
python -m core.llm_view --diff output/diff/<timestamp>.json
python -m core.llm_view --diff output/diff/<timestamp>.json --level lean
python -m core.llm_view --diff output/diff/<timestamp>.json --prompt
```

Useful options:

| Option | Description |
|---|---|
| `--level` | `summary`, `lean`, `standard` (default), or `full` |
| `--include` / `--exclude` | Filter `changes` sections (comma-separated) |
| `--max-chars` | Degrade the level or truncate touched nodes to fit a budget |
| `--max-string-len` | Maximum text value length (default `300`) |
| `--prompt` | Output the complete `<bpmn_change>` prompt block |
| `--stats` | Print character/token estimates to stderr |
| `--pretty` / `--text` | Human-readable JSON or plain text |
| `--out` | Base output path (default: `output/view/<timestamp>.<ext>`) |

`llm_view` only reads a diff produced by `bpmn_diff`; it never parses BPMN or
runs the diff itself. Results are saved to `output/view/` automatically, or to the
`--out` base path. The extension follows the format: `.json` for the default
JSON view, `.txt` with `--text`, and `.md` with `--prompt` (an existing suffix
is replaced).

### 4. Use as a library

```python
from core.bpmn_parser import parse_bpmn
from core.bpmn_diff import diff_files, get_context
from core.llm_view import build_prompt_block, build_view, render_view

old = parse_bpmn("bpmn/old/p2p_test_old.bpmn")
new = parse_bpmn("bpmn/new/p2p_test_new.bpmn")
result = diff_files("bpmn/old/p2p_test_old.bpmn", "bpmn/new/p2p_test_new.bpmn")

view = build_view(result, "standard", models=(old, new))
text = render_view(view)
prompt = build_prompt_block(result, models=(old, new))

ctx = get_context(new, "TASK-ID")
```

`core.bpmn_parser` is API-only: it has no CLI. Use `parse_bpmn` from
Python, or run `python -m core.bpmn_diff` for the file-based workflow.

## Output Format

The diff returns a JSON dict with the keys `schema_version`, `old_file`, `new_file`, `summary`, `nodes`, `flows`, `lanes`, `processes`, `participants`, and `warnings`. Participants are separated from processes; `summary` also contains a `kinds` histogram, a list of `touched_node_ids`, and a count of `warnings`. All lists are sorted by ID so the result is stable regardless of XML order.

Each warning contains a `level` (`info` or `warning`). The parser marks data/definition elements as `info`, while data loss or inconsistent references are marked as `warning`.

The `llm_view` result has `view_version`, `level`, `old`, `new`, `identical`,
`counts`, `kinds`, `warnings`, optional `touched_nodes`/`hints`/`filtered`/
`truncated`, and `changes` sections. Levels are `summary` ⊂ `lean` ⊂ `standard`
⊂ `full`; the default is `standard`. See `core/README.md` for details.
