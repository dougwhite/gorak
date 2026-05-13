# Development

## Setup

```bash
git clone git@github.com:dougwhite/gorak.git
cd gorak
uv sync
```

## Run Checks

```bash
uv run pytest
uv run ruff check .
uv run mypy
```

Format code:

```bash
uv run ruff format .
```

Run the CLI from the checkout:

```bash
uv run gorak --help
```

Install the editable command for use outside the checkout:

```bash
uv tool install --editable .
gorak --help
```

Uninstall:

```bash
uv tool uninstall gorak
```

## Build

```bash
uv build
```

Install the built wheel:

```bash
uv tool install dist/gorak-0.1.0-py3-none-any.whl
```

## Source Layout

```text
src/gorak/cli.py          argparse command handlers
src/gorak/connection.py   backend and env resolution
src/gorak/database.py     direct ODBC metadata reads
src/gorak/export.py       export orchestration and file writes
src/gorak/local.py        local w4gldev/sql wrappers
src/gorak/parser.py       XML parsing and .w4gl/.wml encoding
src/gorak/project.py      project discovery, scaffolding, config
src/gorak/remote.py       SSH/SCP remote helpers
src/gorak/sync.py         database-to-local sync orchestration
src/gorak/sync_state.py   .openroad/gorak-state.json handling
```

CLI tests live under `tests/cli/`. Module tests live under `tests/test_*.py`.

## LLM Summary

Generate a tracked-source summary for external LLM context:

```bash
utils/llm_summary.sh
```

This writes `.llm/summary.md`, which is ignored by git.

## Contributions

Submitted code should be tested, typed, and easy to review.

- Add or update tests for behavior changes.
- Run `uv run pytest`, `uv run ruff check .`, and `uv run mypy` before submitting.
- Keep changes concise and focused on the problem being solved.
- Prefer clear, direct code over broad refactors.
