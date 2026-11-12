# Working on this OpenROAD project

gorak represents OpenROAD applications as readable files that can be edited,
reviewed, and committed with normal development tools. Workbench and gorak share
the configured OpenROAD source database; disk edits are not active in OpenROAD
until they are pushed.

## Workflow

1. Read the project notes and run `git status --short`.
2. Run `gorak status`. Use `gorak pull` for Workbench changes or `gorak sync`
   for changes in both directions.
3. Edit the requested `.w4gl`, `.wml`, application metadata, or field-default
   files.
4. Run `gorak status` to check pending transfers and conflicts.
5. Run `gorak push --compile` and require success.
6. Run `gorak test`. Tests execute database source and never synchronize disk
   changes automatically.
7. Inspect `git status --short` and `git diff`. Commit only the intended files.

Use `gorak push --compile && gorak test` for the routine push-and-test loop.
`gorak test --app APP --component COMPONENT` selects one test entry point.
`gorak run APP --component COMPONENT` runs an application already stored in the
database.

## Source and safety

- Track `.w4gl`, `.wml`, `app.json`, `gorak.json`, `AGENTS.md`, and stylesheet JSON.
  WML stores actual field state; stylesheet files represent the native Style Editor.
  Never infer field values from a stylesheet or add `gorak_style`. Older source
  formats require a fresh export.
- Never commit `.env` or `.openroad/`. The first may contain credentials; the
  second contains transfer checkpoints, locks, and run artifacts.
- Keep WML well formed and preserve established metadata, field names, event
  scripts, and native `fieldstyle` values.
- Keep Workbench source editors closed while gorak imports.
- Resolve conflicts with `gorak push APP/COMPONENT --force` to keep disk source
  or `gorak pull APP/COMPONENT --force` to keep Workbench source. Confirm which
  version to keep before forcing.
- Retry reported failures after fixing them. Do not remove an active operation lock.
- A compiler or test failure is a failure even if source synchronization
  completed. Report it and do not claim the change is finished.
- Use a feature branch and create a pull request when requested. Do not merge
  without the owner's instruction.

Use `gorak --help` and subcommand `--help` for the installed interface. Report
the commands run, test results, and any manual Workbench or visual check that is
still required.
