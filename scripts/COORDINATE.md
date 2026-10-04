# Coordinate a gorak candidate

Owner prompt: **Bring the ecosystem up to the latest gorak candidate.**

1. Read this file and the root/consumer `AGENTS.md` instructions. Find the latest
   published development candidate and its tracking issue. Verify its immutable
   tag commit and contract markers. Use that same candidate for all four tasks.
2. Delegate one isolated consumer review per repo when agents are available:
   `gorak-lsp-rs`, `gorak-frame-designer`, `gorak-vscode-ext`, `openroad_demo`.
   Otherwise review them sequentially. Read current PR diff and CI job logs;
   verify checks used the exact candidate and test the consumer's real behavior.
   Preserve other pins, human fixes, and source. Fix concrete compatibility
   failures on the existing PR branch; do not copy upstream tests as certification.
3. Record each reviewed head SHA, tests/platform evidence, blockers, manual gaps,
   and whether a runtime release is actually needed. Pin-only certification does
   not itself require new binary releases. Re-read PR heads after all reviews;
   discard stale approval if a newer candidate/commit arrived.
4. Update the tracking issue's `Coordinator review` section with one combined
   report. Preserve the machine status block and owner notes. Give the owner a
   single summary: ready PRs, blocked PRs, and the next decision.
5. Do not merge, tag, or release without the owner's instruction. When authorized,
   merge only reviewed current heads after CI passes. Release changed runtime
   dependencies first; update and certify the extension against those exact
   released assets/checksums before proposing a final gorak release. Report any
   missing release gate or propagation automation rather than assuming it exists.

The status workflow starts after root push CI completes; it does not run daily.
It watches downstream PR CI for at most twenty minutes. Later fixes or slow CI
can be refreshed with the **Ecosystem candidate status** workflow's manual tag
input, or by the coordinator during review. CI status and reviewed heads are
separate; neither automatically authorizes merges or releases.
