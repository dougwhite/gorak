# Gorak command reference

This page documents Gorak's normal project, synchronization, execution, and
maintenance commands. Experimental source-storage, database-hook, and journal
research commands are intentionally omitted.

## Contents

- [Projects and configuration](#projects-and-configuration)
- [Inspect and export OpenROAD source](#inspect-and-export-openroad-source)
- [Synchronize source](#synchronize-source)
- [Compile, run, and test](#compile-run-and-test)
- [Remote helpers](#remote-helpers)
- [Maintenance and diagnostics](#maintenance-and-diagnostics)
- [Connection options](#connection-options)

Use `gorak --help` or `gorak COMMAND --help` for the interface installed on
your machine.

## Projects and configuration

### `gorak new NAME [--nogit]`

Creates a Gorak project, a starter application named `NAME`, connection
examples, `AGENTS.md`, field defaults, and `gorak.json`. Git is initialized
unless `--nogit` is supplied.

```sh
gorak new payroll
```

### `gorak new app NAME [--test]`

Creates an empty, disk-only application inside the current project.
`--test` also registers the application in the `tests` array in
`gorak.json`.

```sh
gorak new app payroll_tests --test
```

This does not create the application in OpenROAD or install a testing framework.

### `gorak config OPTIONS`

Writes connection settings to the current project's ignored `.env` file.

```sh
gorak config --backend local --vnode myvnode --database sourcedb
```

Use `--sql-backend` and the `--db-*` options for optional ODBC metadata
access. See [Connection options](#connection-options).

### `gorak config remote OPTIONS`

Shortcut for a remote OpenROAD/Ingres connection. The following options are
required:

- `--host HOST`
- `--user USER`
- `--gorak-root WINDOWS_PATH`
- `--vnode VNODE`
- `--database DATABASE`

```sh
gorak config remote \
  --host windows-pc \
  --user developer \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database sourcedb
```

## Inspect and export OpenROAD source

### `gorak app list [--format json|csv]`

Lists applications in the configured OpenROAD source database. JSON is the
default output format.

### `gorak app export APP [--output DIRECTORY]`

Exports an application into readable Gorak source.

```sh
gorak app export salesapp
```

`--output` selects an explicit destination when running outside a project.

### `gorak component list APP [--format json|csv]`

Lists an application's components.

```sh
gorak component list salesapp --format csv
```

### `gorak component export APP COMPONENT [--output PATH]`

Exports one component.

```sh
gorak component export salesapp main_frame
```

### `gorak component import APP COMPONENT [--dry-run]`

Imports and verifies one existing component from the current project.
`--dry-run` prepares the import without changing OpenROAD.

```sh
gorak component import salesapp calculate_totals --dry-run
gorak component import salesapp calculate_totals
```

For normal project work, prefer `gorak sync --push`.

### `gorak includes list APP`

Lists the applications included by `APP`.

## Synchronize source

### `gorak status`

Compares readable disk source, Gorak's baseline, and the OpenROAD source
database. It prints a read-only JSON plan showing pull, push, unchanged, or
conflicting source.

```sh
gorak status
```

### `gorak sync`

Pulls OpenROAD changes into the current project.

```sh
gorak sync
```

Gorak refuses to overwrite pending disk changes.

### `gorak sync --push [--dry-run]`

Imports disk changes, verifies the result, updates the baseline, and compiles
the affected database source.

```sh
gorak sync --push --dry-run
gorak sync --push
```

`--dry-run` prepares and validates the import without changing OpenROAD.

### `gorak sync --bind`

Verifies and binds an older unbound cache to its configured source target.
Fresh exports bind automatically, so most new projects do not need this option.

### `gorak sync --push --force`

Chooses disk as authoritative for the entire tracked project and rebuilds damaged
tracking while retaining displaced source. It cannot be combined with
`--dry-run` or `--bind`. Use it only after deliberately choosing the disk
version during recovery.

### `gorak recover push [--take disk|database]`

Reconciles an incomplete or damaged push:

```sh
gorak recover push
gorak recover push --take disk
gorak recover push --take database
```

Without `--take`, recovery completes only when disk and database source already
agree. An authority choice applies to the entire tracked project. See
[Push and recovery](push.md) before using it.

## Compile, run, and test

### `gorak compile APP [COMPONENT]`

Compiles source already stored in the OpenROAD database and prints full
diagnostics. Omitting `COMPONENT` force-compiles the application.

```sh
gorak compile salesapp calculate_totals
gorak compile salesapp
```

### `gorak run APP [OPTIONS]`

Runs an application from the configured OpenROAD source database.

```sh
gorak run salesapp --component p4_start --timeout 120
```

Options:

| Option | Purpose |
| --- | --- |
| `--component NAME` | Select the entry component. |
| `--timeout SECONDS` | Set the execution timeout. |
| `--trace` | Print complete trace and process output. |

### `gorak test [OPTIONS]`

Runs the suites configured in `gorak.json`, or a suite selected with
`--app`.

```sh
gorak test
gorak test --app salesapp_tests --component runtests --timeout 120
```

Options:

| Option | Purpose |
| --- | --- |
| `--app APP` | Run one test application instead of configured suites. |
| `--component NAME` | Override the configured entry component. |
| `--timeout SECONDS` | Override the configured timeout. |
| `--trace` | Print complete trace and process output. |

See [Run and Test](run-test.md) for suite configuration and result handling.

## Remote helpers

### `gorak remote install`

Installs or updates Gorak's helper scripts on the configured Windows host.

### `gorak remote check`

Checks that the installed remote helpers match the current Gorak build.

Both commands accept `--host`, `--user`, and `--gorak-root` to override
the project configuration for one invocation. See [Remote Helpers](remote.md).

## Maintenance and diagnostics

### `gorak defaults flatten`

Finds field-default values shared by application layers and promotes them into
the repository `field_defaults.json`.

### `gorak migrate-source`

Converts source created by older pre-alpha Gorak formats into the current compact
representation without changing the database. Existing current-format projects
do not need it.

### `gorak encode XML_FILE [--output PATH]`

Encodes one OpenROAD XML component into a standalone legacy `.w4gl` projection
for inspection. Use application or component export for normal portable source.

### `gorak debug audit XML_FILE [--all] [--missing-only]`

Reports XML nodes that are not represented in Gorak's readable source. Use
`--all` instead of `XML_FILE` to audit cached project exports.
`--missing-only` filters the report.

## Connection options

Commands that access OpenROAD accept these options. Saved `.env` values are
normally more convenient; command-line values override them for one run.

### OpenROAD and SQL backends

| Option | Environment variable | Purpose |
| --- | --- | --- |
| `--backend local|remote` | `GORAK_BACKEND` | Run OpenROAD locally or through SSH. |
| `--sql-backend local|remote|odbc` | `GORAK_SQL_BACKEND` | Query Ingres metadata locally, through SSH, or through ODBC. |
| `--vnode VNODE` | `GORAK_VNODE` | Ingres vnode used by OpenROAD. |
| `--database DATABASE` | `GORAK_DATABASE` | OpenROAD source database. |

If `--sql-backend` is omitted, it follows `--backend`.

### Remote host

| Option | Environment variable | Purpose |
| --- | --- | --- |
| `--host HOST` | `GORAK_REMOTE_HOST` | Windows SSH host. |
| `--user USER` | `GORAK_REMOTE_USER` | SSH username. |
| `--gorak-root PATH` | `GORAK_REMOTE_ROOT` | Windows directory containing Gorak helpers. |

### ODBC metadata

| Option | Environment variable | Purpose |
| --- | --- | --- |
| `--db-driver DRIVER` | `GORAK_DB_DRIVER` | Installed Ingres ODBC driver name. |
| `--db-host HOST` | `GORAK_DB_HOST` | Database server. |
| `--db-listen-address ADDRESS` | `GORAK_DB_LISTEN_ADDRESS` | Ingres listen address, such as `II7`. |
| `--db-database DATABASE` | `GORAK_DB_DATABASE` | Optional ODBC database override. |
| `--db-user USER` | `GORAK_DB_USER` | ODBC username. |
| `--db-password PASSWORD` | `GORAK_DB_PASSWORD` | ODBC password. |

ODBC is optional for normal local and SSH workflows. It changes how Gorak reads
Ingres metadata; OpenROAD export, import, compilation, run, and test still use
the local or remote OpenROAD backend.
