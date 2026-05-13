# Remote Helpers

Remote mode runs OpenROAD export and SQL helper scripts on a Windows OpenROAD
development host over SSH.

## Requirements

- OpenSSH access from the Gorak machine to the Windows host.
- OpenROAD / Ingres tools installed on the Windows host.
- A remote directory for helper scripts, for example `C:\Development\gorak`.

## Configure Remote Access

```bash
gorak config \
  --backend remote \
  --host windows-pc \
  --user developer \
  --gorak-root 'C:\Development\gorak' \
  --vnode myvnode \
  --database sourcedb
```

## Install Helpers

```bash
gorak remote install
```

This copies packaged helper scripts from `src/gorak/remote_scripts/` to the
configured remote root.

Run `gorak remote install` again after upgrading Gorak if new helper scripts are
added.

## Check Helpers

`gorak remote check` verifies that the remote helper manifest is installed and
matches the helper version required by this Gorak build:

```bash
gorak remote check
```

Use it after `gorak remote install`, after upgrading Gorak, or when remote
commands fail in a way that suggests a missing or stale helper script.

If the check reports that helpers are missing or outdated, reinstall them:

```bash
gorak remote install
gorak remote check
```

The check is explicit rather than automatic so normal remote exports and syncs
do not pay an extra SSH round trip.

## What The Helpers Do

| Script | Purpose |
| --- | --- |
| `backup-application.bat` | export one full application XML |
| `backup-component.bat` | export one component XML |
| `get-app-list.bat` | list OpenROAD applications |
| `get-component-list.bat` | list components in one application |
| `get-component-sync-metadata.bat` | read sync change markers for all components |
| `get-include-list.bat` | list included applications |
| `gorak-helpers.json` | helper version and required file manifest used by `gorak remote check` |

The helper scripts write temporary SQL files under the remote Gorak root and
delete them after execution.

## Manual Smoke Tests

List applications:

```bash
ssh -T developer@windows-pc 'C:\Development\gorak\get-app-list.bat myvnode sourcedb'
```

Export a component:

```bash
ssh -T developer@windows-pc 'C:\Development\gorak\backup-component.bat myvnode::sourcedb my_app p4_start'
```

The export helper prints the remote XML path. Gorak downloads that file with
`scp`.

## Current Caveats

- Paths and names with spaces or shell metacharacters need more real-world
  hardening.
- Gorak does not check helper script versions before each remote operation.
  Run `gorak remote check` when you want to verify the installed helper set.
