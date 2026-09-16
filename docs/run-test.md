# Run applications and tests

`gorak run` and `gorak test` execute source already stored in the configured
OpenROAD database. They do not synchronize disk changes first.

Push a source change before running it:

```sh
gorak sync --push
gorak test
```

## Run an application

```sh
gorak run example_app --component p4_start --timeout 120
```

`--component` selects the entry point and `--timeout` sets the maximum runtime.
`gorak run` prints the application's trace and process output.

The command uses `w4gldev rundbapp`. A graphical frame needs an interactive
OpenROAD session; a headless SSH run is suitable for procedures and tests but
does not prove that a GUI opened correctly.

## OpenROAD UnitTestFramework

Gorak's test runner consumes XML results produced by Actian's
[OpenROAD UnitTestFramework](https://github.com/ActianCorp/OpenROAD_UnitTestFramework).
Install that framework and its required applications in the OpenROAD environment
before running a Gorak test suite.

Gorak does not install the framework or discover test applications automatically.
It launches the test entry point, configures the framework's JUnit XML output, and
turns the result into a useful command-line exit status.

## Run one test suite

```sh
gorak test --app example_tests --component runtests
```

The default timeout is 120 seconds. Override it when needed:

```sh
gorak test --app example_tests --component runtests --timeout 300
```

## Configure project test suites

To make bare `gorak test` run one or more suites, add a `tests` array to
`gorak.json`:

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

Suites run sequentially. Command-line `--app`, `--component`, and `--timeout`
override the project configuration.

`gorak new app example_tests --test` creates an empty application directory and
adds it to the project configuration. You must still add the framework dependency,
test source, and a runnable entry component.

## Results and troubleshooting

For each suite, Gorak prints the total tests, failures, errors, and skipped tests.
It exits nonzero when:

- the OpenROAD process fails or times out;
- the XML result is missing, empty, or malformed; or
- the report contains failed or errored tests.

Run artifacts are kept under `.openroad/runs/`, including the original XML
report, trace, process output, and run metadata. Use `--trace` to print complete
trace and process output:

```sh
gorak test --trace
```

Test applications can modify their configured runtime database just as they can
when run from Workbench. Use a disposable test environment where appropriate.
