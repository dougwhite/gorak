# Gorak Configuration Reference

Gorak project configuration lives in `.env`.

After creating a project, copy `.env.example` to `.env` and edit it for your
OpenROAD / Ingres environment:

```bash
cp .env.example .env
```

You can also write these values with [`gorak config`](commands.md#gorak-config).
CLI flags override `.env` values for that run.

## Environment Variables

### Backend

| Variable | Values | Purpose |
| --- | --- | --- |
| `GORAK_BACKEND` | `local`, `remote` | How Gorak runs OpenROAD export commands. |
| `GORAK_SQL_BACKEND` | `local`, `remote`, `odbc` | How Gorak queries Ingres metadata. |

If `GORAK_SQL_BACKEND` is not set, Gorak uses the same backend as
`GORAK_BACKEND`.

### Database

| Variable | Example | Purpose |
| --- | --- | --- |
| `GORAK_VNODE` | `myvnode` | Ingres vnode used by OpenROAD and local SQL commands. |
| `GORAK_DATABASE` | `sourcedb` | OpenROAD source database name. |

### Remote Host

Use these when `GORAK_BACKEND=remote` or `GORAK_SQL_BACKEND=remote`.

| Variable | Example | Purpose |
| --- | --- | --- |
| `GORAK_REMOTE_HOST` | `windows-pc` | SSH host that can run the Windows helper scripts. |
| `GORAK_REMOTE_USER` | `developer` | SSH username. |
| `GORAK_REMOTE_ROOT` | `C:\Development\gorak` | Remote Windows folder containing Gorak helper scripts. |

### ODBC

Use these when `GORAK_SQL_BACKEND=odbc`.

| Variable | Example | Purpose |
| --- | --- | --- |
| `GORAK_DB_DRIVER` | `Ingres AC` | ODBC driver name. |
| `GORAK_DB_HOST` | `db-host.example` | Database host for the ODBC connection. |
| `GORAK_DB_LISTEN_ADDRESS` | `II7` | Ingres listen address. |
| `GORAK_DB_DATABASE` | `sourcedb` | Optional ODBC database override. |
| `GORAK_DB_USER` | `ingres` | ODBC username. |
| `GORAK_DB_PASSWORD` | `secret` | ODBC password. |

If `GORAK_DB_DATABASE` is not set, Gorak uses `GORAK_DATABASE`.

## Example `.env`

### Local

```env
GORAK_BACKEND=local
GORAK_SQL_BACKEND=local
GORAK_VNODE=myvnode
GORAK_DATABASE=sourcedb
```

### Remote

```env
GORAK_BACKEND=remote
GORAK_SQL_BACKEND=remote
GORAK_REMOTE_HOST=windows-pc
GORAK_REMOTE_USER=developer
GORAK_REMOTE_ROOT=C:\Development\gorak
GORAK_VNODE=myvnode
GORAK_DATABASE=sourcedb
```

### Remote Export With ODBC Metadata

```env
GORAK_BACKEND=remote
GORAK_SQL_BACKEND=odbc
GORAK_REMOTE_HOST=windows-pc
GORAK_REMOTE_USER=developer
GORAK_REMOTE_ROOT=C:\Development\gorak
GORAK_VNODE=myvnode
GORAK_DATABASE=sourcedb

GORAK_DB_DRIVER=Ingres AC
GORAK_DB_HOST=db-host.example
GORAK_DB_LISTEN_ADDRESS=II7
GORAK_DB_USER=ingres
GORAK_DB_PASSWORD=secret
```
