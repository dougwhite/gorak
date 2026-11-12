# Push and pull

`gorak push` sends local changes to the source database. `gorak pull` brings
Workbench changes into the checkout. `gorak sync` does both. Use `--dry-run`
to preview transfers and conflicts.

| Where you run it | Target | Scope |
| --- | --- | --- |
| Project root | None | Project |
| Project root | `APP` | Application |
| Application directory | None | Current application |
| Application directory | `COMPONENT` | Component in that application |
| Either | `APP/COMPONENT` or `'APP!COMPONENT'` | Named component |

Quote `'APP!COMPONENT'` in Bash to prevent history expansion. Name an untracked
application to pull it into a project that already has apps. Transfer the
application first if it is missing on the receiving side.

`gorak status` lists pending pushes, pulls, and conflicts. A transfer stops
before writing if its scope contains conflicts. Choose a version explicitly:

- `gorak push APP/COMPONENT --force` keeps the local version.
- `gorak pull APP/COMPONENT --force` keeps the Workbench version.
- `gorak sync --force-push` or `--force-pull` chooses the winner for overlaps
  and still transfers independent changes. An application push can remain
  pending if it would overwrite a component kept from Workbench.

Use `push --full` or `pull --full` to include unchanged sender source in scope.
`--full` still checks for conflicts. Keep Workbench editors closed during
imports. Use `--no-compile` to import source without compiling.

Successful items are checkpointed in `.openroad/transfers.json`. Independent
items continue after a failure, and the command exits nonzero. Fix the error
and retry the pending items.
Handle deletions and local renames in Workbench.
