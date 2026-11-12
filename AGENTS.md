# Working on gorak

Always spell `gorak` in lowercase, including headings, UI text, commits, PRs and
release titles.

This repository develops the Python CLI. OpenROAD application projects are
separate folders containing `gorak.json`; their workflow is packaged in
[`src/gorak/templates/AGENTS.md`](src/gorak/templates/AGENTS.md).

## Development

Use Python 3.12 and `uv`. After behavior changes run:

```sh
uv run pytest
uv run ruff check .
uv run mypy
```

- Format changed Python files with `uv run ruff format`. Keep CLI handlers
  separate from domain logic. Make focused changes; update tests and docs for
  behavior changes. Parser changes need parser/fixture coverage.
- Keep the README short; command reference belongs in `docs/`. See
  [development](docs/development.md) and [test isolation](docs/testing.md).
- Automated tests must use repository fixtures and temporary directories, never
  developer projects or connection files. Mock external services: no real SSH,
  SCP, ODBC or OpenROAD calls from the unit suite. Preserve the isolation guards.
- Keep one packaged Windows helper source under `src/gorak/remote_scripts/`.
  Helper changes require `gorak remote install` on authorized test hosts.

## Source and live acceptance

- Follow [files and formats](docs/files.md): WML stores explicit field state;
  `field_defaults.json` and frame sidecars represent native Style Editor
  stylesheets. Never infer field values from stylesheets or introduce
  `gorak_style`. Older source formats require a fresh export.
- Unknown XML layouts must retain a safe fallback or explicit refusal. Never
  bypass a rejected source push with direct SQL writes.
- Live acceptance requires an explicitly authorized disposable environment.
  Keep Workbench editors closed during imports and follow
  [push and pull](docs/push.md). Resolve conflicts before proceeding; report
  failures and retry pending items. Use disposable projects to test deletions.
- Require successful `gorak push` before `gorak test`: tests execute database
  source and do not synchronize disk edits. Report failed checks and unavailable
  manual acceptance honestly.
- Preserve safety tests for experimental tracking, revision, journal,
  native-source and encoded-source code. Do not promote these into the public
  workflow without the owner's direction.

## Working tree and publication

- Inspect the working tree before changes and the diff/staged content before
  commits. Preserve unrelated files; do not discard work or force-push.
- Never commit `.env`, `.openroad/`, caches or private source. Do not publish
  proprietary source, private application/corpus identifiers, machine or database
  identities, credentials or raw runtime logs. Use neutral synthetic fixtures
  and examples.
- Use a feature branch; create a PR when requested. Do not merge, tag or release
  without the owner's instruction.
- For ecosystem-wide candidate reviews, follow
  [coordinator instructions](scripts/COORDINATE.md).
