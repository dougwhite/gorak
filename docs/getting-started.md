# First OpenROAD project

Gorak is early alpha. Use an independent disposable source database and an
independent runtime database if your application's tests modify data. Export a
backup through Workbench before experimenting. Do not change the target of an
existing Gorak cache to point at a different database.

## Prerequisites

- Python 3.12 or newer, Git, and preferably `uv`.
- A licensed OpenROAD development installation with `w4gldev`, its standard image
  libraries, and an Ingres client configured to reach your source database.
- Local execution uses the initialized OpenROAD command environment. SSH execution
  uses the packaged Windows batch/PowerShell helpers. Linux clients can use SSH;
  an installed Linux Python package alone cannot run Windows OpenROAD.
- SSH/SCP access and PowerShell on a remote Windows execution host. Current helper
  version is 8; run `gorak remote install` after upgrading Gorak. Python 3.12 on the
  execution host is additionally required for managed-revision writer mode.
- Ingres ODBC client/driver and its driver-manager registration when selecting
  `GORAK_SQL_BACKEND=odbc`. ODBC is required for managed revision/native tools,
  optional for the ordinary XML workflow. It does not replace `w4gldev` execution.
- Live acceptance currently covers a Linux client with SSH to OpenROAD 12 on
  Windows. Broader platform/version compatibility requires testing; Python's
  supported version range is not an OpenROAD compatibility promise.

Use your OpenROAD/Ingres installation's supported database-creation and source
repository initialization process. Have the DBA create a disposable database
rather than copying internal source tables manually. On the rehearsed Ingres
installation a standard database was created using `createdb TARGET -no_x100`;
that is installation-specific. Open and initialize it through Workbench as needed.
No journal/revision installer is required for the ordinary workflow.

## Install and create

```sh
git clone https://github.com/dougwhite/gorak.git
cd gorak
uv sync
uv tool install --editable .
gorak --help
gorak new myproject
cd myproject
cp .env.example .env
```

On PowerShell use `Copy-Item .env.example .env`. `gorak new --nogit myproject`
skips `git init`. The scaffold includes a starter app named after the project;
that app is disk-only until pushed. If your aim is only to export an existing app,
remove this untouched starter app directory before the first push, or give the
project the same name as the app you intend to export. Never remove an app that
has already been synchronized as a way to request database deletion.

`gorak new app example_app` creates an empty disk application inside an existing
project. `gorak new app example_tests --test` also registers it as a test suite,
but does not install a framework or create a test entry point.

## Configure a source connection

For local OpenROAD execution, edit `.env`:

```dotenv
GORAK_BACKEND=local
GORAK_SQL_BACKEND=local
GORAK_VNODE=myvnode
GORAK_DATABASE=disposabledb
```

The vnode and database are separate values. Do not paste `node::database` into
the database setting. Run the command in a shell with the same initialized
OpenROAD environment that works for your installation's command-line tools.

For SSH execution:

```dotenv
GORAK_BACKEND=remote
GORAK_SQL_BACKEND=remote
GORAK_REMOTE_HOST=windows-host.example
GORAK_REMOTE_USER=developer
GORAK_REMOTE_ROOT=C:\Development\gorak
GORAK_VNODE=myvnode
GORAK_DATABASE=disposabledb
```

Then run `gorak remote install` and `gorak remote check`. Verify SSH host keys
normally. The helpers must resolve the correct OpenROAD installation; see
[remote setup](remote.md). Never put passwords into shell history or tracked files.

For direct ODBC metadata queries, retain your local/remote execution settings and
set `GORAK_SQL_BACKEND=odbc`, then supply the `GORAK_DB_*` driver/host/listen/user
settings in [configuration](config.md). `GORAK_DB_DATABASE`, if specified, must
refer to the same source repository as `GORAK_DATABASE`.

## Export, edit, push, test

```sh
gorak app list
gorak component list example_app
gorak includes list example_app
gorak app export example_app
gorak status
```

An existing exported cache may need `gorak sync --bind`; this verifies its source
against the configured database before recording the target. Do not erase caches
when binding fails. A fresh cache-free synchronization can bind automatically.
Export is an explicit source-writing operation: use a fresh/clean project for the
initial export. Use `gorak sync` for subsequent safe pulls.

```sh
gorak sync
# Make a supported source change.
gorak status
gorak sync --push --dry-run
gorak sync --push && gorak test
```

A dry run prepares/validates push XML but does not import it. Bare `gorak test`
requires suites in `gorak.json`; see [test configuration](run-test.md). To run a
specific suite, use `gorak test --app example_tests --component runtests`.
`gorak run example_app --component p4_start` selects an application entry point.
Interactive frames require an interactive session; SSH is suitable for headless
procedures/tests, not proof of visible GUI behavior.

For a single existing component, `gorak component import example_app p4_start`
uses the same readable reconstruction and component conflict check. Prefer the
project-wide push loop for ordinary work.

## Failures and reset

`status` returns a JSON change plan. `push` actions are disk changes; `pull`
actions are database changes; divergent changes are conflicts. Pull refuses all
pending local changes, and push refuses pending database changes. An error is not
a request to force the operation. Read the named `.openroad` artifacts and
[recovery guide](synchronization.md).

`.openroad/` stores ignored baselines, target binding, operation/recovery journals,
locks and run logs/results. Complete format-2 readable source needs no XML
companions. Run `gorak migrate-source` once for legacy projects; keep its recovery
evidence under `.openroad`. See [formats and migration](files.md).

To test a clean clone against another disposable database, use a **new checkout**,
configure its own `.env`, install its required source/image dependencies, and run
`gorak sync --push`. Do not move an existing binding or delete its state. For a
repeatable demo reset, restore only the known demo source files from the baseline
commit and push them through Gorak; preserve all recovery and binding metadata.
Database removal is a separate DBA operation after Workbench/writers are closed.
