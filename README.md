# Gorak — the Greater OpenROAD Application Kit

Work with OpenROAD source in VS Code, Git, and AI coding agents. Gorak exports
applications into readable 4GL source and frame markup, synchronizes explicit
changes with an OpenROAD source database, and runs application tests from the CLI.

> **Early alpha.** Formats and compatibility are still evolving. Start with a
> disposable source database and backed-up source, never your production repository.
> Imports are verified but are not a transaction across an entire application set.

The everyday loop is explicit:

```sh
gorak sync                       # pull latest before editing
# edit readable .w4gl / .wml source
gorak sync --push && gorak test   # import/compile, then test database source
git diff                         # inspect before committing or opening a PR
```

`gorak test` does **not** synchronize source. `gorak status` inspects disk,
baseline and database changes. Conflicts stop synchronization rather than choosing
whichever timestamp is newest.

## Get started

You need Python 3.12+, Git, and an initialized OpenROAD/Ingres development
installation, either locally or on a Windows host reached through SSH. See the
[onboarding guide](docs/getting-started.md) for prerequisites, connection settings,
disposable database setup, and the first export.

```sh
git clone https://github.com/dougwhite/gorak.git
cd gorak
uv sync
uv tool install --editable .
gorak new myproject
cd myproject
cp .env.example .env
# Configure .env for your disposable source database.
gorak app list
gorak app export example_app
```

New projects include an `AGENTS.md` explaining the correct edit → push → test
workflow. Existing projects can adopt the [agent instructions](docs/agent-workflow.md).

## What works, and what is experimental

The normal path uses OpenROAD XML export/import, preserves opaque XML companions,
and verifies imported source. Existing procedures/classes, frame logic and layout,
and represented component metadata use the same conflict and recovery gates.
[Component editing](docs/component-editing.md) describes the tested types and limits;
[rehearsal evidence](docs/demo/rehearsal.md) distinguishes automated and live checks
from visual acceptance. Fresh procedure/class creation and portable application
restoration are also available. Source deletion pushes remain unsupported.

Optional [managed revision acceleration](docs/revision-mode.md) retains its writer
and DBA generation contract. [Native source archives](docs/native-source.md),
[journal diagnostics](docs/journal.md), and [direct source decoding](docs/research/encoded-source.md)
are specialist facilities, not onboarding prerequisites. Watch mode, automatic
synchronization and broad native source writes are future work.

## Documentation

- [Getting started](docs/getting-started.md) · [Configuration](docs/config.md)
- [Commands](docs/commands.md) · [Synchronization and recovery](docs/synchronization.md)
- [Component editing](docs/component-editing.md) · [Push](docs/push.md)
- [Run and test](docs/run-test.md) · [Files and portable source](docs/files.md)
- [Remote helpers](docs/remote.md) · [Demo rehearsal](docs/demo/rehearsal.md)
- [Development](docs/development.md) · [Longer-term roadmap](docs/demo/README.md)
