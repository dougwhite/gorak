# Writer-session revision acceptance

Date: 2026-09-14. Follow-up to [revision-token experiments](revision-token-acceptance.md).
These are isolated SQL experiments, not a tracking-schema upgrade. Randomly named
ordinary user-owned scratch objects were removed after every run. OpenROAD source
and installed tracking were not changed.

## Candidate and reproducible SQL shape

The candidate keys a retained counter by the calling server and session. The
source table in this experiment contains only an integer primary key and payload.
The following is the tested SQL shape, using generic example names. Execute only
in a disposable database; these statements create real tables and source rules.

```sql
create table session_probe_source (
    id integer not null primary key, payload integer not null
);
create table session_probe_revisions (
    server_id varchar(64) not null,
    session_id varchar(64) not null,
    revision bigint not null,
    primary key(server_id, session_id)
);
modify session_probe_source to btree on id with page_size=8192;
modify session_probe_revisions to btree on server_id,session_id with page_size=8192;

create procedure session_probe_bump() as begin
    update session_probe_revisions set revision=revision+1
    where server_id=dbmsinfo('ima_server')
      and session_id=dbmsinfo('session_id');
    if iirowcount=0 then
        insert into session_probe_revisions
        values(dbmsinfo('ima_server'),dbmsinfo('session_id'),1);
    endif;
end;

create rule session_probe_i after insert on session_probe_source
    execute procedure session_probe_bump;
create rule session_probe_u after update on session_probe_source
    execute procedure session_probe_bump;
create rule session_probe_d after delete on session_probe_source
    execute procedure session_probe_bump;
```

DDL is committed before opening concurrent source transactions. Initial tests use
`set lockmode session where level=mvcc, readlock=shared, timeout=3` in each ODBC
session. Reader assertions use fresh transactions. ODBC pooling is disabled before
opening connections for reconnect tests. Cleanup drops the three rules, procedure,
and two tables after closing/rolling back writer sessions.

## Passed live checks

- Rules recorded the same server/session identity observed directly by each caller.
  Two concurrently connected writers had distinct keys.
- An uncommitted first-use counter remained invisible to a committed reader.
  Rolling back that source transaction also removed the newly initialized counter.
- A second writer initialized its own counter and committed while the first writer
  remained uncommitted. One run measured 2.251 ms for that source insert/commit.
- Two writers each performed further mutations of distinct source rows. Both
  committed, in 2.924 and 3.834 ms, without the source-partition revision cycle from
  the previous experiment. Each stayed on its own counter across all mutations.
- Update and delete increments became visible on commit and disappeared on rollback.
- Closing a connection with a pending first-use source insertion left neither the
  source insertion nor its new counter committed.
- Twenty sequential connections received **one reused server/session key** on the
  tested server. The retained counter increased on every committed insertion;
  reconnect did not reset it. This is observed reuse, not a uniqueness guarantee.
- Reading the three retained counters with a reader commit took 0.404 ms median,
  1.446 ms maximum over 50 warm samples. This is a small isolated measurement, not
  a production performance bound.

## Concurrent consolidation: integrity passed, writer availability failed

A separate experiment transferred one counter into a persistent base total:
within one transaction, delete the row conditional on its observed revision, then
add that revision to the base. A fresh reader calculated base plus the sum of
retained counters in a single SQL statement.

Before consolidation committed, the reader still saw the original total. A source
writer resumed while its counter row was deleted but uncommitted. After the
consolidator committed, the writer was rejected with SQLSTATE 40001 and rolled
back. The total remained correct. A later source write recreated the counter and
increased the total correctly.

**Decision:** do not use this as transparent online cleanup. Preserving the total
is insufficient when cleanup can reject a legitimate Workbench save. The experiment
used a short deliberate overlap; it is not a proof of every race or isolation mode.

## Writer lock mode is part of the contract

Separate tests seeded two counter rows and changed only the revision table's lock
mode. Source tables continued using MVCC, isolating the added tracking contention.
One writer updated source and held its transaction; the other changed a different
source row and therefore a different counter.

| Revision-table lock mode | Second writer outcome |
| --- | --- |
| PAGE | Timed out after 2.014 seconds, SQLSTATE 5000P |
| ROW | Committed in approximately 3 ms |
| MVCC | Independent writes passed in the earlier tests |

Different counter rows can occupy the same page. Separate keys alone do not
prevent contention for a page-locking writer. These tests do not establish the
actual Workbench or compiler session settings. Installing counters without checking
those settings would be premature. Configuring only Gorak's ODBC reader cannot
change the locks acquired by Workbench writers.

## Decision and next implementation boundary

Writer-specific counters remain promising **under verified row/MVCC writer locking**.
The tested design does not yet meet the deployment contract for arbitrary clients.

Next work should establish the writer configuration contract for Workbench and
CLI import/compile paths, including whether a table-specific row-lock setting can
be applied reliably. Preserve current tracking until that contract is proven.
Do not change global database lock defaults based on these experiments.

For an initial implementation, prefer retained counters and a bounded observation
budget over online deletion: if the budget is exceeded, use full comparison and
report that maintenance is needed. Counters must never reset solely because a
session disconnects or its identifier is reused. This limits the fast path's read
work; it does not itself bound database storage. A generation-changing maintenance
procedure with an explicit quiescence requirement needs its own acceptance.

Also pending: multiple DBMS servers, server restart/address reuse, identifier
length validation, counter overflow, independent users under owner-defined rules,
physical restore, large counter populations, and interaction with source journal
checkpoint/retention. No source-validation token is integrated into normal status
or sync, and the full-export oracle remains required.

## Primary references

The server address and internal session identifier come from
[DBMSINFO](https://docs.actian.com/actianx/12.0/SQLRef/DBMSINFO_Function.htm).
That documentation does not make the pair a durable connection identity.
The procedure's row-count branch follows
[Effects of Errors in Database Procedures](https://docs.actian.com/ingres/12.0/SQLRef/Effects_of_Errors_in_Database_Procedures.htm).
Lock granularity is documented in
[Lock Levels](https://docs.actian.com/actianx/12.0/DatabaseAdmin/Lock_Levels.htm).
