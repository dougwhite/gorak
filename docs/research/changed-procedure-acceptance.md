# Changed-procedure ODBC acceptance

Verified on 2026-09-14 using an isolated OpenROAD 12 source database, a disposable
application containing one integer procedure, a temporary revision extension, and
an isolated local checkout. Only the test Workbench launcher was modified. Source
edits used Workbench or OpenROAD XML import; no direct SQL source writes were used.

## Supported observation

`GORAK_SOURCE_DECODING=procedures_v1` is an explicit opt-in alongside managed
revisions. Full XML establishes the semantic inventory. Up to 128 current simple
procedures can enroll only when the entire decoded component signature matches
that inventory. Larger enrollment sets deliberately disable the procedure shortcut;
this is not large-corpus certification.

Changed vectors use a bounded event range certified by the sum of per-lane revision
increments. Every old/new affected identity must resolve to an enrolled procedure
or its guarded application. At most 4096 events and 128 affected identities are
accepted; unknown ownership, missing events and late lower-ID commits require full
comparison. Neither event allocation order nor component timestamps authorize reuse.

Workbench description saves were observed to update the entity row, delete and
reinsert the component row, update encoded storage, and update application metadata.
The reader therefore checks the **final** component row and decodes the complete
supported graph. It also checks application/base/version metadata. Component and
application alteration date/count/user bookkeeping is excluded; component compile
state is excluded because the encoded graph is still examined. All other columns,
including unfamiliar metadata, remain guarded. Application source changes, entity
replacement/deletion, includes and shared storage still require full XML.

The supported graph is the strict uncompiled integer-procedure form documented in
[encoded-source research](encoded-source.md). Complete metadata guards and the XML
oracle are necessary; extracting recognizable script text alone is insufficient.

## Live results

These are individual fresh-CLI-process samples on a small isolated application,
not tail-latency or larger-project guarantees. Oracle exports ran separately after
the timed status and are not included in its time.

| Operation | Time | Result |
| --- | ---: | --- |
| Initial full bootstrap | 1.181 s | Full XML, procedure enrolled |
| Quiet status | 0.370 s | Revision reuse |
| First Workbench description save, before save-path handling | 1.283 s | Explicit full fallback; XML agreed |
| First status after another description save, with final guards | **0.397 s** | ODBC procedure refresh, no XML |
| First status after script changed from return 0 to return 1 | **0.412 s** | ODBC procedure refresh, no XML |

Both successful changed-source observations matched the **entire semantic hash
inventory and three-way plan** from subsequent fresh full XML, including the exact
description/script. They were the first status calls after the respective saves,
not repeated quiet checks.

A divergent disk script edit was classified as conflict. Real push preflight
rejected it with exit 1, and the revision vector remained unchanged. The scratch
disk file was restored afterward. Component replacement via XML import remained
an explicit identity fallback and agreed with XML; it took approximately 1.18 s.

## Safety and limits

Before/after complete vectors and installation checks still bracket observation and
publication. Dirty refresh preserves the original full-oracle timestamp; the
15-minute expiry does not slide. Target/scope/generation changes, expired/corrupt
snapshots, partial vectors and unknown forms cannot authorize selective reuse.
Explicit full-reference disagreement quarantines the generation. Push mutation-time
checks and full-XML pull staging are unchanged.

Automated regressions cover bounded ranges, late commits, missing identities,
chunk corruption/limits, embedded delimiters, complete XML fixtures, guarded
application/component metadata, Workbench row replacement, conflicts, oracle
mismatch/quarantine, concurrent writes and non-sliding expiry. Broader procedures,
compiled graphs, Unicode, frames/classes, general application decoding, cross-app
ownership and large-corpus latency remain open.

The original Workbench batch file was copied to the disposable helper directory;
only the revision-table `ING_SET` suffix was added. Minimal reconstructed launchers
failed on log/profile setup and were replaced with the user's working launcher.
The normal launcher was not edited. Keep the actual known-working launch environment
for future acceptance instead of reconstructing it from selected settings.

Final live cleanup checks also passed: compiling the procedure produced an
unsupported graph and explicitly used full XML (1.779 s in-process); the separate
oracle agreed. Deleting the disposable application was detected before removing the
revision extension. The scratch application, extension and helper/launcher directory
were removed, and the original parent tracking identity and structural health were
preserved. The user closed the temporary Workbench instance before cleanup.

Final automated verification: **818 pytest tests passed**, Ruff passed, and strict
mypy passed. Automated tests do not connect to developer services.
