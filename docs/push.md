# Push and recovery

For normal work, inspect and push readable disk changes with:

```sh
gorak status
gorak sync --push
```

Use a dry run when you want Gorak to prepare and validate the import without
changing OpenROAD:

```sh
gorak sync --push --dry-run
```

Keep Workbench source editors closed while Gorak imports source.

## What a push does

Gorak:

1. compares disk, baseline, and current OpenROAD source;
2. refuses conflicts or unexpected database changes;
3. reconstructs and imports the planned source;
4. re-exports it to verify the readable source contract;
5. installs the verified synchronization baseline; and
6. compiles the affected database source.

A compiler error makes `gorak sync --push` exit nonzero, but it does not undo a
successfully verified source import. Use the printed command to see full compiler
diagnostics:

```sh
gorak compile example_app component_name
gorak compile example_app
```

These commands compile source already stored in OpenROAD, not unpushed disk files.

Gorak does not currently perform ordinary database-side component deletion.
Removing a tracked component on disk, or finding a tracked component missing from
OpenROAD, is treated as a conflict unless you deliberately choose an authoritative
side during recovery.

## Retry an interrupted push

An interrupted command can normally be retried:

```sh
gorak sync --push
```

Gorak keeps the submitted source and before-images under `.openroad/`. On retry
it compares that evidence with a fresh OpenROAD export, recognizes source that
OpenROAD already accepted, and continues safely.

Do not delete `.openroad/`, baselines, locks, or pending-operation files to make
an error disappear. They are the evidence Gorak uses to avoid overwriting work.

## Resolve a recovery state

First inspect the current state:

```sh
gorak status
gorak recover push
```

A plain `gorak recover push` completes recovery only when disk and database
already agree.

If they differ, choose an authoritative side only after inspecting both versions:

```sh
gorak recover push --take disk
gorak recover push --take database
```

The choice applies to the entire tracked project, not only the first component
named in the error. Before replacing anything, Gorak retains displaced readable
source, baselines, and database exports under `.openroad/pushes/`.

`--take disk` imports local source but does not delete database-only components.
`--take database` replaces tracked readable source while leaving unrelated
project files alone.

```sh
gorak sync --push --force
```

This uses the same disk-authority policy and can rebuild damaged baselines. It
still requires the project to be bound to the configured source target and does
not bypass validation or post-import verification.

If you cannot establish which side is authoritative, stop and preserve both. Do
not guess merely to clear the recovery state.

## Artifacts

Push evidence and compiler logs are stored under `.openroad/`, including:

- `.openroad/pushes/` for submitted source, before-images, and recovery evidence;
- `.openroad/imports/` for individual component-import artifacts; and
- `.openroad/compiles/` for explicit compiler logs.

These files can contain source and connection identities. Keep them private and
out of Git.
