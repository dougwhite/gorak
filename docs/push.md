# Transfer workflows

## Workbench first

Edit in Workbench, then run `gorak pull` to update your checkout. Use
`gorak app export APP` the first time you bring an app into the project.

## Repo first

Run `git pull` or edit the files, then run `gorak push` to send changes
to OpenROAD. Run `gorak compile` when you want to compile database source.

## Two way

After editing on both sides, run `gorak status` to see what changed, then
`gorak sync` to transfer changes. If sync reports a conflict, choose the
version to keep and rerun sync:

- `gorak push APP/COMPONENT --force` keeps the local version.
- `gorak pull APP/COMPONENT --force` keeps the Workbench version.

See the [command reference](commands.md#synchronize-source) for scopes and options.
