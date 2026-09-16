# Remote helpers

Remote mode lets Gorak run OpenROAD and Ingres command-line tools on a Windows
development machine over SSH. Use it when the Gorak project and Git tools live on
Linux or another workstation.

## Requirements

The Windows host needs:

- a licensed OpenROAD development installation;
- an Ingres client configured for the source database;
- Windows OpenSSH Server and an SSH account you can connect to;
- PowerShell; and
- a directory where Gorak can install its helper scripts, such as
  `C:\Development\gorak`.

Confirm that SSH works and accept the host key normally before configuring Gorak.

## Configure the project

From the Gorak project:

```sh
gorak config remote \
  --host windows-pc \
  --user developer \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database sourcedb
```

This stores the connection in the project's ignored `.env` file. Host, user,
and path values can also be supplied to individual commands with `--host`,
`--user`, and `--gorak-root`.

## Install and check the helpers

```sh
gorak remote install
gorak remote check
```

`remote install` copies the helper scripts required by the current Gorak build
to the configured Windows directory. Run it again after upgrading Gorak.

`remote check` verifies that the installed helper manifest matches the current
build. If it reports missing or outdated helpers, reinstall them:

```sh
gorak remote install
gorak remote check
```

## Use normal Gorak commands

After setup, the normal commands use the remote host automatically:

```sh
gorak app list
gorak app export myapplication
gorak sync
gorak sync --push
gorak test
```

OpenROAD export, import, compilation, run, and test happen on the Windows host.
Files returned by Gorak are stored in the local project.

ODBC remains optional. If configured, it can read Ingres metadata directly from
the Gorak machine while OpenROAD execution continues over SSH. See the
[Configuration Guide](config.md#optional-odbc-metadata-access).

## Limitations

- Interactive graphical frames need an interactive OpenROAD session. A headless
  SSH run is suitable for procedures and tests but does not prove that a window
  was displayed.
- Remote paths and names containing unusual shell metacharacters may need extra
  care.
- Gorak does not check the helper manifest before every command; use
  `gorak remote check` after upgrades or when remote execution fails.
