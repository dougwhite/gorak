# Push and pull

`gorak push` sends changed readable source to the configured database. Local
source wins. `gorak pull` sends changed database source to the checkout. Database
source wins. Neither command compares receiver content or reconciles conflicts.

`gorak sync` aliases pull; `gorak sync --push` aliases push. Use `--full` to
transfer everything, `--dry-run` to preview, and `push --no-compile` for source
imports without compilation. Keep Workbench editors closed during imports.

The transfer ledger in `.openroad/transfers.json` records successful file hashes
and database IDs, names, and alteration tokens. A missing ledger or changed target
starts a full transfer. A receiver-only edit is left alone until the sender changes
or a full transfer is requested. The source format is unchanged.
Deletions are not propagated. Local renames/deletions require a native database
operation; database renames are detected by identity and name when pulling.

A failed component or application is reported while independent items continue.
Successful items are recorded; failed items remain pending. The command exits
nonzero if any item failed or was skipped. Retry after correcting the failure.
Source import success does not establish successful compilation or execution.

Git provides source history. No three-way baselines or recovery snapshots are
created by push/pull. Never commit `.env` or `.openroad/`.
