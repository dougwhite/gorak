# Working on this OpenROAD project

gorak represents OpenROAD applications as readable files that can be edited,
reviewed, and committed with normal development tools. Workbench and gorak share
the configured OpenROAD source database; disk edits are not active in OpenROAD
until they are pushed.

## Workflow

1. Read the project notes and run `git status --short`.
2. Choose the sender: `gorak pull` overwrites local files from changed database
   components. Use it when Workbench is authoritative, not before uploading local work.
3. Edit the requested `.w4gl`, `.wml`, application metadata, or field-default
   files.
4. Run `gorak status` to inspect the planned disk/database changes.
5. Run `gorak push` and require success.
6. Run `gorak test`. Tests execute database source and never synchronize disk
   changes automatically.
7. Inspect `git status --short` and `git diff`. Commit only the intended files.

Use `gorak push && gorak test` for the routine push-and-test loop.
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
- Push uses local file hashes; pull uses database IDs, names, and change tokens.
  The sender wins. Failed items remain pending; successful items are checkpointed.
  Retry failures with the same command. Do not remove an active operation lock.
- A compiler or test failure is a failure even if source synchronization
  completed. Report it and do not claim the change is finished.
- Use a feature branch and create a pull request when requested. Do not merge
  without the owner's instruction.

Use `gorak --help` and subcommand `--help` for the installed interface. Report
the commands run, test results, and any manual Workbench or visual check that is
still required.
