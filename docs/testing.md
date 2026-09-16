# Test isolation and repository examples

Automated tests must be self-contained. Use committed Gorak fixtures and pytest
`tmp_path` directories; do not read developer projects, local source repositories,
connection files, or live application databases.

The autouse fixture in `tests/conftest.py` removes inherited Gorak and unit-test
runtime configuration and blocks real ODBC connections and external subprocesses.
The suite can run without unixODBC: database logic uses mocked engines, and only
tests that instantiate native `pyodbc` exceptions skip when it cannot be imported.
Fresh-process regression tests block the driver import to exercise help, project
creation, local/SSH dispatch, and the missing-runtime ODBC error.
Mock backend calls explicitly. Runner tests may execute fake programs created inside
the current test's temporary directory. This guard covers the existing backend
boundaries; it is not an operating-system sandbox.

Use fictional usernames, hosts, databases, application names, and example paths in
source, tests, fixtures, documentation, and commit messages. Never copy real
connection details or raw acceptance logs into tracked files. Generic Windows paths
are command-format examples, not dependencies on an installed environment.

Live acceptance is separate from pytest. Keep its connection settings and raw
artifacts outside the tracked repository and record only sanitized outcomes here.
Before committing, inspect staged content and the commit message for identifying
names, absolute personal paths, addresses, and credentials. Removing a reference
from the current tree does not remove it from Git history.

Run the automated checks from the Gorak checkout:

```sh
uv run pytest
uv run ruff check .
uv run mypy
```
