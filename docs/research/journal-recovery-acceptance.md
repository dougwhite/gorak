# Journal recovery and observation-window acceptance

Checkpoint: 2026-09-14. Tests used the current schema-v2 installation in an isolated
OpenROAD source database and a temporary copy of a four-application checkout.
Actual ODBC queries and OpenROAD application exports over SSH were used.

Only tracking metadata was changed. Original application source and the working
demo were untouched. Journal events were inserted deliberately for these consumer
and publication tests; this does not extend source-hook coverage.

## Consumer recovery

1. Bootstrap a full-reference observation.
2. Insert one synthetic journal event, consume it in the test consumer and publish
   its exact-ID acknowledgment. Polling that consumer returns no pending events.
3. Run rebootstrap while keeping the installation UUID unchanged.
4. Verify the replacement consumer has a different UUID and sees the same event
   again. Verify the archive retains the old consumer UUID and its acknowledgment.
5. Change the isolated installation marker UUID.
6. Verify normal selective verification rejects the old consumer binding.
7. Rebootstrap against the new identity, then run normal verification successfully.
   The event remains pending for the replacement consumer.

All checks passed. The synthetic event was acknowledged with a test-only no-op
callback because it represented no source mutation. This must not be used as a
recipe for acknowledging real source changes without processing them.

The changed marker simulates an installation identity change. No physical database
restore was performed. These results establish recovery behavior for retained and
changed identities, not automatic restore detection or survival of event history.

## Late commit during export

A separate fresh installation and checkout tested the observation-window guard:

1. Commit event 20.
2. Insert event 10 in an independent ODBC transaction and leave it uncommitted.
3. Read the committed observation: count 1, maximum 20.
4. Begin normal snapshot verification. Immediately after its first real application
   export returns, commit the pending writer transaction.
5. The final observation reads count 2, maximum 20.
6. Verify publication fails with a journal-change diagnostic and the prior snapshot
   pointer is byte-for-byte unchanged.
7. Retry with the writer finished; full-reference verification succeeds.

All checks passed. The actual export function was wrapped solely to choose the
commit point; database observation and publication checks used production code.
This proves that the current guard catches this lower-ID commit even though a
maximum-only comparison would miss it.

It does not prove atomic multi-application exports, complete event batches,
detection of changes outside hook coverage, or commits after the final observation.
It is not a throughput or large-history benchmark.

## Cleanup and retained evidence

Both probes removed their temporary tracking tables, rules, procedure and sequence.
The temporary writer grant disappeared with its table. Installation checks confirmed
no test tracking objects remained. Local JSON reports, XML snapshots and archived
consumer databases were retained outside version control.

The recovery protocol remains explicit and per checkout. Normal status/sync still
require full comparisons. The next correctness gates include source-hook coverage
across Workbench/frame/shared-storage operations, physical restore acceptance and
a coordinated generation/invalidation strategy, followed by a scalable alternative
to counting retained journal history.
