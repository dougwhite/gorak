# Working on this OpenROAD project

Gorak represents OpenROAD applications as app folders containing `app.json`,
readable `.w4gl` source (TOML metadata, then `===`, then 4GL), and frame `.wml`
markup. Workbench and Gorak share a configured source database; disk edits are
not active in that database until pushed.

## Ordinary workflow

1. Read this file and project notes. Run `git status --short`, then `gorak sync`
   before editing. Pull refuses to overwrite pending local work. If it refuses,
   inspect `git diff` and `gorak status`; do not discard someone else's work.
2. Edit the requested `.w4gl` scripts/declarations or `.wml` layout/event code.
   Keep XML well formed and OpenROAD identifiers within 32 characters.
3. Run `gorak status` if you need to inspect the three-way change plan.
4. Run `gorak sync --push` and require success, then run `gorak test`.
   The shorter routine loop is `gorak sync --push && gorak test`.
   `gorak test` NEVER synchronizes disk edits automatically.
5. Inspect `git status --short` and `git diff`, including tests and any canonical
   WML returned after OpenROAD coordinate conversion. Commit only the intended
   files. Use a feature branch and create a pull request when requested. Do not
   merge a pull request without the owner's instruction.

`gorak test --app example_tests --component runtests` selects a suite entry point.
Bare `gorak test` runs suites configured in `gorak.json`; it does not discover tests.
`gorak run example_app --component p4_start` runs existing database source.
A graphical frame needs an interactive OpenROAD session; an SSH process is not
proof that a window was shown. Tests may run application-defined database writes:
use a disposable source/runtime environment.

## Source ownership and safety

- Track `.w4gl`, `.wml`, `app.json`, `gorak.json`, field-default JSON and exported
  `.gorak-source/` XML companions. Companions preserve structures not represented
  by readable source. Let Gorak maintain them; do not hand-edit their internals.
- `.env` contains local connection settings and secrets. Never commit it or print
  credentials. `.openroad/` is ignored: it contains target bindings, XML baselines,
  operation journals, locks, recovery evidence and run/test artifacts.
- Edit field defaults deliberately: inherited values can affect multiple frames.
  Unknown XML/property shapes are rejected rather than guessed. Newly authored
  frames still require a preserved frame baseline; do not invent companion XML.
- A conflict means disk and database changed relative to their common baseline.
  Stop, retain both versions, inspect the reported component and ask the owner
  which change to reconcile. There is no ordinary force/overwrite workflow.
- A refused or interrupted push may have partially updated the database. Retain
  its artifacts. `gorak recover push` can verify and finish only when both sides
  agree; it does not choose a winner or roll back database writes.
- Never bypass a refusal by deleting locks, caches, pending markers, quarantine,
  baselines, generation metadata or target bindings. Never use direct SQL writes
  as a shortcut. Escalate unresolved recovery to the owner.
- `gorak status`, `gorak sync`, scoped edits, `gorak sync --push`, and configured
  tests are routine operations within an authorized feature request. Stop on a
  failure; do not test stale source and report the feature complete.
- `gorak source ...`, journal diagnostics, installation/reset SQL, native restore,
  and revision-generation administration are specialist operations, outside the
  ordinary feature workflow. Existing managed revision settings must be preserved;
  never disable validation or remove quarantine to get a demo to pass.

Use `gorak --help` and subcommand `--help` for the installed interface. Report the
commands actually run, test results, and any outstanding manual visual check.
