# gorak

GORAK — the Greater OpenROAD Application Kit.

> Warning: gorak is in early alpha. Source file formats are subject to change.
> Consider carefully before using this utility in a mission-critical or production environment.

## Setup

We recommend you install [`uv`](https://docs.astral.sh/uv/) for the best development experience.

Clone the repo and install vendor packages:

```bash
git clone https://github.com/dougwhite/gorak.git
cd gorak
uv sync
```

Run the test suite:

```bash
uv run pytest
```

Install the tool in editable mode:

```bash
uv tool install --editable .
```

## Quickstart

You can now run gorak like so:

```bash
gorak --help
```

Create a new gorak project:

```bash
gorak new myproject
cd myproject
```

This will create the following project layout (with example application):
```
myproject
├── .env.example
├── field_defaults.json
├── .gitignore
├── gorak.json
└── myproject
    ├── app.json
    └── p4_init.w4gl
```

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Modify `.env` to match the correct Ingres/OpenROAD environment:

```env
GORAK_BACKEND=local
GORAK_VNODE=myvnode
GORAK_DATABASE=exampledb
```

> See the [Configuration Guide](docs/config.md) for more information on alternate backends.

Export an application from your OpenROAD repo:

```bash
gorak app export myapplication
```

To sync new component changes:

```bash
gorak sync
```

## Full Documentation

- [Community Demo and Roadmap](docs/demo/README.md) - Planned walkthrough, missing capabilities, and acceptance milestones

- [Full Command List](docs/commands.md) - List of all commands and CLI parameters explained
- [Configuration Guide](docs/config.md) - Customize how gorak communicates with OpenROAD / Ingres
- [Synchronization](docs/synchronization.md) - Status, target binding, conflicts, and current limits
- [Run and Test](docs/run-test.md) - Execute applications and collect unit-test results
- [Native Source Snapshots](docs/native-source.md) - Experimental XML-free ODBC export and fresh-database restoration
- [Component Import](docs/import.md) - Import existing procedure and class script edits
- [Files And Formats](docs/files.md) - Overview of the file formats and project layouts gorak uses
- [Remote Helpers](docs/remote.md) - How to use gorak with a remote Windows OpenROAD host
- [Development Guide](docs/development.md) - Guide to contributing to the gorak project

## Project Goals

Gorak aims to make OpenROAD projects work like modern source code projects.

The primary goal is to let developers work on an OpenROAD application entirely
from VS Code, with OpenROAD Workbench acting as a build artifact server rather
than the source of truth.

Gorak is focused on:

- A useful CLI for day-to-day OpenROAD development.
- Human-readable, text-based OpenROAD source and metadata.
- Git source control for OpenROAD applications.
- Two-way sync between local source files and OpenROAD repositories.

Optional [managed revision mode](docs/revision-mode.md) gives status and push a
verified quiet path using ODBC revision tokens. It requires the documented writer
and DBA generation contract. An explicit experimental procedure decoder can also
refresh supported description/script changes through ODBC; other changes retain
full XML comparison. See the [scope and measured acceptance](docs/research/changed-procedure-acceptance.md).
