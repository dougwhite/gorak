set lockmode session where readlock=shared, timeout=5;
\g
select revision_id from "$ingres".gorak_revision_install;
\g
\q
