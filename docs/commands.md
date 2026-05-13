# Gorak Command Reference

Brief reference for the commands currently exposed by the `gorak` CLI.

## Table Of Contents

- [Help](#help)
  - [`gorak --help`](#gorak---help)
  - [`gorak COMMAND --help`](#gorak-command---help)
- [Creating A New Gorak Project](#creating-a-new-gorak-project)
  - [`gorak new NAME`](#gorak-new-name)
  - [`gorak config`](#gorak-config)
- [Querying The Database](#querying-the-database)
  - [`gorak app list`](#gorak-app-list)
  - [`gorak component list APP`](#gorak-component-list-app)
  - [`gorak includes list APP`](#gorak-includes-list-app)
- [Exporting Components](#exporting-components)
  - [`gorak app export APP`](#gorak-app-export-app)
  - [`gorak component export APP COMPONENT`](#gorak-component-export-app-component)
  - [`gorak sync`](#gorak-sync)
- [Misc](#misc)
  - [`gorak debug audit [XML_FILE]`](#gorak-debug-audit-xml_file)
  - [`gorak defaults flatten`](#gorak-defaults-flatten)
  - [`gorak encode XML_FILE`](#gorak-encode-xml_file)
- [Gorak Remote](#gorak-remote)
  - [`gorak remote install`](#gorak-remote-install)
  - [`gorak remote check`](#gorak-remote-check)
- [Shared Connection Flags](#shared-connection-flags)
  - [Backends](#backends)
  - [Database Configuration](#database-configuration)
  - [Remote Host Flags](#remote-host-flags)
  - [ODBC Database Params](#odbc-database-params)
  - [Connection Examples](#connection-examples)

## Help

### `gorak --help`

Shows top-level CLI help.

Flags: none.

```bash
gorak --help
```

### `gorak COMMAND --help`

Shows help for a command or command group.

Flags: none.

```bash
gorak app list --help
```

## Creating A New Gorak Project

### `gorak new NAME`

Creates a new Gorak project.

Flags:

| Flag | Purpose |
| --- | --- |
| `--nogit` | Skip `git init`. |

```bash
gorak new example_project
```

### `gorak config`

Saves connection settings to the current project's `.env` file.

Flags:

| Flag | Purpose |
| --- | --- |
| Shared connection flags | See [Shared Connection Flags](#shared-connection-flags). |

```bash
gorak config --backend local --sql-backend local --vnode myvnode --database sourcedb
```

## Querying The Database

### `gorak app list`

Lists OpenROAD applications.

Flags:

| Flag | Purpose |
| --- | --- |
| `--format json` | Print JSON output. |
| `--format csv` | Print CSV output. |

```bash
gorak app list --format json
```

### `gorak component list APP`

Lists components in an application.

Flags:

| Flag | Purpose |
| --- | --- |
| `--format json` | Print JSON output. |
| `--format csv` | Print CSV output. |

```bash
gorak component list salesapp --format csv
```

### `gorak includes list APP`

Lists included applications.

Flags: none.

```bash
gorak includes list salesapp
```

## Exporting Components

### `gorak app export APP`

Exports an application to source files.

Flags:

| Flag | Purpose |
| --- | --- |
| `--output DIRECTORY` | Output directory when running outside a Gorak project. |

```bash
gorak app export salesapp
```

### `gorak component export APP COMPONENT`

Exports one component to a source file.

Flags:

| Flag | Purpose |
| --- | --- |
| `--output PATH` | Output path when running outside a Gorak project. |

```bash
gorak component export salesapp main_frame
```

### `gorak sync`

Checks out-of-date components and re-exports them to source files.

Flags: none.

```bash
gorak sync
```

## Misc

### `gorak debug audit [XML_FILE]`

Audits `.xml` export files and determines which nodes are not represented in
exported source files.

> Note: This is not a guarantee of coverage, but rather a supplementary tool to
> analyze and identify holes in gorak's implementation.

Flags:

| Flag | Purpose |
| --- | --- |
| `--all` | Audit all cached project XML exports. |
| `--missing-only` | Only show missing coverage. |

```bash
gorak debug audit frame.xml --missing-only
```

### `gorak defaults flatten`

Identifies common field defaults and promotes them to app and project
`field_defaults.json` files.

Flags: none.

```bash
gorak defaults flatten
```

### `gorak encode XML_FILE`

Encodes a single OpenROAD XML source file into `.w4gl` format.

Flags:

| Flag | Purpose |
| --- | --- |
| `--output PATH` | Write output to a file instead of stdout. |

```bash
gorak encode component.xml --output component.w4gl
```

## Gorak Remote

### `gorak remote install`

Installs or updates the Windows helper scripts on a remote host.

Flags:

| Flag | Purpose |
| --- | --- |
| `--user USER` | SSH username. |
| `--host HOST` | SSH host. |
| `--gorak-root PATH` | Remote Windows Gorak root. |

```bash
gorak remote install --user developer --host windows-pc --gorak-root 'C:\Development\gorak'
```

### `gorak remote check`

Checks the installed Windows helper scripts on a remote host are up to date.

Flags:

| Flag | Purpose |
| --- | --- |
| `--user USER` | SSH username. |
| `--host HOST` | SSH host. |
| `--gorak-root PATH` | Remote Windows Gorak root. |

```bash
gorak remote check --user developer --host windows-pc --gorak-root 'C:\Development\gorak'
```

## Shared Connection Flags

These flags tell Gorak how to communicate with OpenROAD and Ingres.
Pass them on the command line for one run, or save them with `gorak config` so
they live in the project `.env`.

### Backends

- `--backend` specifies how gorak should communicate with `w4gldev.exe`, either
  locally or remotely over SSH.
- `--sql-backend` determines how gorak should query Ingres: through command
  line `sql.exe`, remotely over SSH, or directly via ODBC.

Remote SSH operation requires a Windows host configured for OpenSSH connections.
ODBC connections require the Ingres ODBC driver to be set up.

| Flag | Environment variable | Purpose |
| --- | --- | --- |
| `--backend local` | `GORAK_BACKEND=local` | Run OpenROAD export commands on this machine. |
| `--backend remote` | `GORAK_BACKEND=remote` | Run OpenROAD export commands over SSH on a Windows host. |
| `--sql-backend local` | `GORAK_SQL_BACKEND=local` | Query metadata with local Ingres `sql`. |
| `--sql-backend remote` | `GORAK_SQL_BACKEND=remote` | Query metadata through the remote helper scripts. |
| `--sql-backend odbc` | `GORAK_SQL_BACKEND=odbc` | Query metadata directly through ODBC. |

### Database Configuration

The following flags are used to point gorak at the correct OpenROAD repository:

| Flag | Environment variable | Purpose |
| --- | --- | --- |
| `--vnode VNODE` | `GORAK_VNODE` | Ingres vnode used by OpenROAD and local SQL commands. |
| `--database DATABASE` | `GORAK_DATABASE` | OpenROAD source database name. |

### Remote Host Flags

When using `--backend remote`, the following flags apply:

| Flag | Environment variable | Purpose |
| --- | --- | --- |
| `--user USER` | `GORAK_REMOTE_USER` | SSH username for the remote host. |
| `--host HOST` | `GORAK_REMOTE_HOST` | SSH host that can run OpenROAD helper scripts. |
| `--gorak-root PATH` | `GORAK_REMOTE_ROOT` | Remote Windows folder where Gorak helper scripts live. |

### ODBC Database Params

When querying component metadata over ODBC, the following flags can be used.

| Flag | Environment variable | Purpose |
| --- | --- | --- |
| `--db-driver DRIVER` | `GORAK_DB_DRIVER` | ODBC driver name. |
| `--db-host HOST` | `GORAK_DB_HOST` | Database host for the ODBC connection. |
| `--db-listen-address ADDRESS` | `GORAK_DB_LISTEN_ADDRESS` | Ingres listen address, such as `II7`. |
| `--db-database DATABASE` | `GORAK_DB_DATABASE` | Optional ODBC database override. |
| `--db-user USER` | `GORAK_DB_USER` | ODBC username. |
| `--db-password PASSWORD` | `GORAK_DB_PASSWORD` | ODBC password. |

### Connection Examples

Example 1: Local exports and metadata queries

```bash
gorak app list --backend local --sql-backend local --vnode myvnode --database sourcedb
```

Example 2: Remote exports and metadata queries over SSH

```bash
gorak app export salesapp \
  --backend remote \
  --sql-backend remote \
  --user developer \
  --host windows-pc \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database sourcedb
```

Example 3: Remote exports with ODBC-based metadata queries

```bash
gorak sync \
  --backend remote \
  --sql-backend odbc \
  --user developer \
  --host windows-pc \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database sourcedb \
  --db-driver 'Ingres AC' \
  --db-host db-host.example \
  --db-listen-address II7 \
  --db-user ingres \
  --db-password secret
```

Example 4: Local exports with ODBC-based metadata queries

```bash
gorak component list salesapp \
  --backend local \
  --sql-backend odbc \
  --vnode myvnode \
  --database sourcedb \
  --db-driver 'Ingres AC' \
  --db-host db-host.example \
  --db-listen-address II7 \
  --db-user ingres \
  --db-password secret
```
