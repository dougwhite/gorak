# Run applications and tests

Run an application already stored in the configured OpenROAD source database:

```sh
gorak run example_app --component p4_start --timeout 120
```

Run the OpenROAD unit framework's suite entry point:

```sh
gorak test --app example_tests --component runtests
```

These commands do not import, sync, or replace source. They use `w4gldev rundbapp`
and accept the standard local/remote connection flags. ODBC is an independent
metadata backend; application execution always uses OpenROAD locally or via SSH.
Local execution requires an initialized OpenROAD environment. Remote execution
requires Windows PowerShell and helper version 9 (`gorak remote install`).

RunDBApp uses the application's saved runtime database; this command does not
override it. `--database` selects the source repository. Test applications may
modify test data, including schema setup, just as when run from Workbench.

## Configured suites

For `gorak test` without `--app`, configure one or more suites in `gorak.json`:

```json
{
  "name": "example",
  "tests": [
    {
      "application": "example_tests",
      "component": "runtests",
      "timeout_seconds": 120
    }
  ]
}
```

String entries such as `"example_tests"` are also accepted. CLI component,
and timeout flags override configured values. Applications run
sequentially; a failed assertion does not prevent the next configured suite from
running. Default timeout is 120 seconds. No automatic suite discovery is performed.

## Trace and runtime environment

Configure these local-only settings in project `.env`:

```dotenv
# Persistent is the default. Without TRACE_DIR, remote logs use the Gorak
# installation's traces folder; local logs use the local run artifact folder.
GORAK_TRACE_MODE=persistent
GORAK_TRACE_DIR=C:\temp

# Pass application-specific environment values to the execution host.
GORAK_RUN_ENV_OR_UNITTEST_TESTDIR=C:\Development\tests
GORAK_RUN_ENV_OR_UNITTEST_TMPDIR=C:\temp
GORAK_RUN_ENV_II_LIBU3GL=kernel32.dll;user32.dll;gdi32.dll;advapi32.dll;comdlg.dll;ntdll.dll;msvcrt.dll
```

All `GORAK_RUN_ENV_` values are passed to the child with that prefix removed.
They can configure application settings, timezone, date format, test resources,
and a remote `II_SYSTEM`. Keep credentials in `.env`, never `gorak.json`.
The runner owns the framework's statistics-output variables during test runs,
overriding inherited values to prevent stale reports being reused.

Set `GORAK_TRACE_MODE=temp` for temporary execution-host logs. The remote helper
returns their contents before removing its temporary directory. Local copies of
trace/results remain under `.openroad/runs/ID/` for diagnosis. Temporary mode
ignores TRACE_DIR. Persistent directories on the remote host must be absolute.
Each run uses unique filenames; remote trace names include application and user.

## Results and failures

`gorak test` enables `OR_UNITTEST_GEN_XML_STATS` and directs
`OR_UNITTEST_STATSFILE_XML` to a unique file. It prints counts and individual
failure/error messages, and retains the original JUnit-shaped XML as
`.openroad/runs/ID/results.xml`. The framework may count setup methods as tests.

Exit code is zero only when execution succeeds and the report is valid, complete,
nonempty, and contains no failed/error tests. Missing or malformed reports and
timeouts fail the command. The Actian framework's process code 2 is accepted as
success only with a valid report containing skipped tests and no failures/errors.
Other nonzero process codes fail. A failed report is detected even if the process exits
zero. `gorak run` reports process success only; it does not interpret test results.

Each run also saves `trace.log`, `process.log`, and `run.json`. Use `--trace` to
print full trace and process output when testing. Plain `gorak run` prints it by
default. Log delivery occurs after execution, not as a live stream. Transport
failure is reported separately; a disconnected SSH client does not prove that
remote execution has stopped. The remote helper enforces its own deadline and
terminates its launched process tree on timeout.

The test XML can be used by compatible JUnit tooling. VS Code test discovery,
source navigation adapters and keybindings are not installed by these commands.


With [managed revision mode](revision-mode.md), run/test validates the configured
revision generation and uses the shared execution-host startup worker. SSH requires
Python 3.12+ and current helpers. Test result semantics are unchanged, including
intentional failures and the fact that testing does not implicitly sync source.
