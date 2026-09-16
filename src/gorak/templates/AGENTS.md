# Working on this OpenROAD project

Gorak represents OpenROAD applications as readable files that can be edited,
reviewed, and committed with normal development tools. Workbench and Gorak share
the configured OpenROAD source database; disk edits are not active in OpenROAD
until they are pushed.

## Workflow

1. Read the project notes and run `git status --short`.
2. Run `gorak sync` before editing. If it refuses because disk changes are
   pending, inspect `git diff` and `gorak status`; do not discard existing work.
3. Edit the requested `.w4gl`, `.wml`, application metadata, or field-default
   files.
4. Run `gorak status` to inspect the planned disk/database changes.
5. Run `gorak sync --push` and require success.
6. Run `gorak test`. Tests execute database source and never synchronize disk
   changes automatically.
7. Inspect `git status --short` and `git diff`. Commit only the intended files.

Use `gorak sync --push && gorak test` for the routine push-and-test loop.
`gorak test --app APP --component COMPONENT` selects one test entry point.
`gorak run APP --component COMPONENT` runs an application already stored in the
database.

## Source and safety

- Track `.w4gl`, `.wml`, `app.json`, `gorak.json`, `AGENTS.md`, and
  field-default JSON.
- Never commit `.env` or `.openroad/`. The first may contain credentials; the
  second contains local baselines, target binding, locks, recovery evidence,
  temporary XML, and run artifacts.
- Keep WML well formed, preserve established metadata structure, and keep field
  names and event scripts consistent. Preserve `gorak_style="N"` selectors unless
  you deliberately know which inherited OpenROAD style the field should use.
- Keep Workbench source editors closed while Gorak imports.
- A conflict means disk and OpenROAD both changed relative to their common
  baseline. Stop, preserve both versions, and ask which version is authoritative.
- An interrupted push can normally be retried with `gorak sync --push`. Do not
  bypass a refusal by deleting `.openroad/`, locks, baselines, pending markers,
  or target binding.
- Recovery commands such as `gorak recover push --take disk|database` choose an
  authoritative side for the whole tracked project. Use them only with the
  owner's explicit direction.
- A compiler or test failure is a failure even if source synchronization
  completed. Report it and do not claim the change is finished.
- Use a feature branch and create a pull request when requested. Do not merge
  without the owner's instruction.

Use `gorak --help` and subcommand `--help` for the installed interface. Report
the commands run, test results, and any manual Workbench or visual check that is
still required.
