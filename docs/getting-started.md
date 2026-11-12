# Getting started

This guide covers the simplest gorak setup: OpenROAD and gorak running on the
same development machine, using OpenROAD's normal command-line tools.

> **Early alpha.** Start with a disposable OpenROAD source database and keep a
> Workbench backup. Do not use a production source database.

## Requirements

- A licensed OpenROAD development installation, including `w4gldev`, with an
  Ingres client configured to reach your source database.
- Python 3.12 or newer.
- [`uv`](https://docs.astral.sh/uv/).
- Git.

gorak can also run OpenROAD on another Windows machine over
[SSH](remote.md). Direct [ODBC metadata access](config.md#optional-odbc-metadata-access)
is available but is not required for this guide or the normal workflow.

## Install gorak

Clone the gorak repository and install the command:

```sh
git clone https://github.com/dougwhite/gorak.git
cd gorak
uv sync
uv tool install --editable .
gorak --help
```

Run gorak from a shell initialized for your OpenROAD and Ingres installation.
In PowerShell, with `II_SYSTEM` set to the selected installation root:

```powershell
$env:PATH = "$env:II_SYSTEM\ingres\bin;$env:II_SYSTEM\ingres\utility;$env:PATH"
```

## Create a project

```sh
gorak new myproject
cd myproject
```

gorak creates a Git repository, project metadata, connection examples, agent
instructions, shared field defaults, and a small starter application called
`myproject`.

This walkthrough will export an existing application, so delete the untouched
starter application:

```sh
rm -r myproject
```

On PowerShell:

```powershell
Remove-Item -Recurse myproject
```

Only delete this untouched starter directory. Deleting a synchronized application
directory is not a request to delete that application from OpenROAD.

## Connect to your source database

Configure the local OpenROAD backend:

```sh
gorak config --backend local --vnode myvnode --database sourcedb
```

This writes the local connection settings to `.env`, which is ignored by Git.
Use separate values for the vnode and database; do not write
`myvnode::sourcedb` in the database setting.
Before running a restored application, check its runtime `database_name` in
`app.json`. It can differ from the source database in `.env`.

Check the connection by listing the applications in the source database:

```sh
gorak app list
```

See the [Configuration Guide](config.md) for all settings, ODBC, and remote
connections.

## Export an existing application

List the source components if you want to inspect the application first:

```sh
gorak component list myapplication
```

Pull it into the project and record its transfer checkpoint:

```sh
gorak pull myapplication
```

The new application directory contains `app.json`, readable `.w4gl` source,
frame `.wml`, and any application field defaults. gorak keeps local
synchronization state under the ignored `.openroad/` directory.

## Make the initial Git commit

Review the exported source and commit the clean starting point:

```sh
git status
git add .
git commit -m "Initial OpenROAD source export"
```

The tracked project is now a normal Git repository. Do not add `.env` or
`.openroad/`.

## Push a change back to OpenROAD

Use `gorak pull` to retrieve Workbench changes or `gorak sync` to transfer
changes in both directions. See [conflict resolution](push.md) if both sides changed.

Edit a supported `.w4gl` or `.wml` file, then inspect gorak's planned changes:

```sh
gorak status
```

Push the disk change into the OpenROAD source database:

```sh
gorak push myapplication
```

gorak imports and compiles the changed source. If the application has
configured tests, run them after a successful push:

```sh
gorak test
git diff
```

`gorak test` runs the source already stored in OpenROAD; it never pushes disk
changes automatically.

Failed items remain pending; correct the reported failure and retry the same command.
Pending compilation is retried by `gorak push` without repeating successful imports.

## Upgrading existing projects

Old baselines and fresh Git clones have no shared transfer checkpoint. When
source exists on both sides, gorak reports a conflict. Save pending work and
preview with `gorak sync --dry-run`. Use `gorak pull APP --force` to start from
Workbench or `gorak push APP --force` to start from the checkout.
