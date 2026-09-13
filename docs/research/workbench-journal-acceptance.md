# Workbench journal acceptance

Checkpoint: 2026-09-14. A human operator performed these actions in Workbench on a
disposable fixture application in the isolated research database. Between actions,
Gorak polled the journal, mapped application candidates and exported the application
again. The committed journal observation was checked across each export.

The generated schema-v2 installation and production application mapper were used.
Verified event batches were acknowledged only in the dedicated temporary acceptance
consumer after recording the comparison result. Common checkout baselines were not
advanced.

## Results

| Workbench action | Events | Mapping | Export verification |
|---|---:|---|---|
| Save procedure with a harmless comment | 5 | Target app, no fallback | Comment present; only procedure script changed |
| Save a frame button label | 32 | Target app plus full fallback | Expected label present; only frame changed; scripts unchanged |
| Rename procedure | 10 | Target app, no fallback | Old name absent, new name present, script identical |
| Delete renamed procedure | 5 | Target app, no fallback | Procedure absent; remaining scripts unchanged |
| Create frame numbered version | 33 | Target app, no fallback | Version 1 present alongside current version; current export unchanged |
| Change application description | 7 | Target app, no fallback | Description present; only application metadata changed |
| Remove an included-application relationship | 5 | Target app plus full fallback | Relationship absent; included application itself preserved |

All actions were detected. A full fallback is a safe diagnostic result, not a
successful selective-invalidation result. This evidence does not enable fast status.

## Storage behavior

The procedure save updated an entity, encoded source and application row, and
deleted/reinserted a component row.

The frame label save updated 29 encoded-object rows and an application row, and
deleted/reinserted a component row. There was no entity event. The mapper requested
full comparison because the deleted component lacked sufficient historical
ownership evidence.

Rename generated new entity/component/encoded rows and deleted the old rows,
alongside application updates. Captured ancestry was sufficient to identify the
application. Workbench left the procedure script text unchanged in this probe.

Deletion retained enough entity history for mapping after the component disappeared.

The numbered version created an entity, a component row and 30 encoded rows, and
updated a component row. Version metadata reported current version -1 and numbered
version 1. Journal activity did not imply a current-source edit.

Saving the application description deleted and reinserted its two include rows
although the include values stayed unchanged. Removing one include subsequently
deleted both rows and reinserted the remaining row. The latter batch lacked the
historical context required by the conservative mapper, so it requested full
comparison rather than trusting current identity alone.

## Consequences

Ordinary Workbench operations are now represented in the live acceptance record.
Frame saves and include removal are concrete performance cases for improving
historical ownership capture or resolution. Any improvement must preserve fallback
for missing history, identity reuse and unresolved ancestry; simply trusting a
current matching ID would weaken correctness.

Events remain invalidations, not source diffs. Semantic export comparison correctly
distinguished a numbered-version save from a current-source edit.

Remaining coverage includes component moves across applications, application
rename/deletion through Workbench, version restore/purge, concurrent editors,
Unicode fidelity, shared-storage source ownership and larger save transactions.
This seven-action sequence is bounded acceptance, not complete Workbench coverage.

## Retained state

The disposable application and its tracking installation remain in the isolated
database pending closure of Workbench editors and subsequent cleanup. The raw
before/after XML, journal summaries and dedicated consumer remain in temporary local
storage. The original applications and the user's working project were not edited.
Machine-specific identifiers and raw source exports are not tracked in git.
