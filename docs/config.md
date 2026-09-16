# Configuration guide

Gorak project connection settings live in the ignored `.env` file. The
`gorak config` command creates or updates it:

```sh
gorak config --backend local --vnode myvnode --database sourcedb
```

You can also copy `.env.example` to `.env` and edit it directly. Command-line
connection options override `.env` values for one invocation.

For normal local or SSH operation, ODBC is optional.

## Local OpenROAD

Use this when Gorak runs in a shell that can already execute your OpenROAD and
Ingres command-line tools:

```env
GORAK_BACKEND=local
GORAK_VNODE=myvnode
GORAK_DATABASE=sourcedb
```

If `GORAK_SQL_BACKEND` is omitted, Gorak uses the same backend for metadata
queries.

The vnode and database are separate values. Do not put `myvnode::sourcedb` in
`GORAK_DATABASE`.

## Remote OpenROAD over SSH

Use this when Gorak runs on another machine and executes OpenROAD on a Windows
development host:

```sh
gorak config remote \
  --host windows-pc \
  --user developer \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database sourcedb
```

This writes:

```env
GORAK_BACKEND=remote
GORAK_REMOTE_HOST=windows-pc
GORAK_REMOTE_USER=developer
GORAK_REMOTE_ROOT=C:\Development\gorak
GORAK_VNODE=myvnode
GORAK_DATABASE=sourcedb
```

Complete the setup with:

```sh
gorak remote install
gorak remote check
```

See [Remote Helpers](remote.md) for host requirements and setup.

## Optional ODBC metadata access

Set `GORAK_SQL_BACKEND=odbc` when you want Gorak to query Ingres metadata
directly through an installed Actian Ingres ODBC driver:

```env
GORAK_BACKEND=local
GORAK_SQL_BACKEND=odbc
GORAK_VNODE=myvnode
GORAK_DATABASE=sourcedb

GORAK_DB_DRIVER=Ingres AC
GORAK_DB_HOST=db-host.example
GORAK_DB_LISTEN_ADDRESS=II7
GORAK_DB_USER=ingres
GORAK_DB_PASSWORD=secret
```

ODBC changes only the metadata-query path. OpenROAD export, import, compilation,
run, and test still use `GORAK_BACKEND=local` or `remote`.

`GORAK_DB_DATABASE` is an optional ODBC database override. If omitted, Gorak
uses `GORAK_DATABASE`. If supplied, it must identify the same OpenROAD source
repository.

## Environment variables

| Variable | Values or example | Purpose |
| --- | --- | --- |
| `GORAK_BACKEND` | `local`, `remote` | How Gorak executes OpenROAD commands. |
| `GORAK_SQL_BACKEND` | `local`, `remote`, `odbc` | How Gorak queries Ingres metadata. |
| `GORAK_VNODE` | `myvnode` | Ingres vnode used by OpenROAD. |
| `GORAK_DATABASE` | `sourcedb` | OpenROAD source database. |
| `GORAK_REMOTE_HOST` | `windows-pc` | SSH host used by the remote backend. |
| `GORAK_REMOTE_USER` | `developer` | SSH username. |
| `GORAK_REMOTE_ROOT` | `C:\Development\gorak` | Remote helper directory. |
| `GORAK_DB_DRIVER` | `Ingres AC` | ODBC driver name. |
| `GORAK_DB_HOST` | `db-host.example` | ODBC database host. |
| `GORAK_DB_LISTEN_ADDRESS` | `II7` | Ingres listen address. |
| `GORAK_DB_DATABASE` | `sourcedb` | Optional ODBC database override. |
| `GORAK_DB_USER` | `ingres` | ODBC username. |
| `GORAK_DB_PASSWORD` | `secret` | ODBC password. |

Keep credentials in `.env`, never in tracked project files or copied command
output.
