# Shared-storage API acceptance and source-editing investigation

Checkpoint: 2026-09-14. The temporary headless probe used OpenROAD 12.0, the current
schema-v2 tracking installation and the isolated research database.

## Documented storage APIs

StringObject and BitmapObject expose InsertIntoDB, UpdateInDB and DeleteFromDB.
StringObject accepts a table name for insertion, and subsequent operations use its
DBHandle. The methods participate in database transactions. The probe checked each
method's status and explicitly committed each successful mutation.

References: [StringObject methods](https://docs.actian.com/openroad/11.2/SysRefSum/StringObject_Methods.htm),
[BitmapObject methods](https://docs.actian.com/openroad/11.2/SysRefSum/BitmapObject_Methods.htm),
[transaction handling](https://docs.actian.com/openroad/11.2/Programming/How_You_Can_Manage_Transactions_with_Bitmaps__St.htm),
[method errors](https://docs.actian.com/openroad/11.2/Programming/How_You_Can_Use_BitmapObject_and_StringObject_Me.htm).

The authored [probe procedure](probes/probe.w4gl) is retained for repeatability.
It must run as the starting procedure of a disposable application connected to a
disposable database. It commits real storage changes; it is not a read-only
diagnostic or a normal unit test. A failure can leave a committed payload requiring
inspection. Return codes 11-13 identify ordinary string failures, 31-33 explicit
nstring-table failures, and 21-23 bitmap failures.

## Live result

The procedure was imported and compiled, setup events were consumed separately,
and it was run through the actual headless OpenROAD CLI over SSH. It returned zero.
It inserted, updated and deleted:

- A StringObject in the default string table.
- A StringObject explicitly targeting ii_stored_nstrings.
- A generated 8-by-8 BitmapObject, including a pixel change before update.

The resulting journal batch contained 15 events: five each from ii_stored_strings,
ii_stored_nstrings and ii_stored_bitmaps. The mapper returned no application
candidates and requested full comparison because shared ownership is unresolved.
The probe did not assign runtime storage objects to the application merely because
their numeric identifiers might match source entity IDs.

The nstring test used ASCII text. It exercises the nstring table through OpenROAD,
not Unicode fidelity, normalization, supplementary characters or multilingual
source round trips. This is runtime storage API acceptance, not proof of which
storage paths Workbench uses to persist components.

## Cleanup detail

DeleteFromDB removed payload rows but left one empty row with identifier -1 in each
table. Their increasing row_sequence values suggest allocation metadata; this
interpretation is not a documented storage contract.

All three tables were verified empty before this series of isolated tests. After
the temporary application and tracking objects were removed, the exact remaining
empty rows were inspected and removed to restore that baseline. Final read-only
checks confirmed empty storage tables and absent tracking objects.

Do not apply this cleanup to ordinary databases or reset allocation rows as part
of normal Gorak operation. Existing handles and other applications must be preserved.
No reference application source was modified.

## Source-editing API investigation

The installed PropertyChanger source delegates processing to ElementManager,
FieldManager and Assistant classes supplied by sourceelements.img. The inspected
installation contains that image but the filename search did not locate its source.

Actian documents PropertyChanger as an image and customizable source application:
[run the Upgrade Assistant](https://docs.actian.com/openroad/11.2/Migration/Run_the_Upgrade_Assistant.htm).
The inspected example has a GUI-driven workflow. No standalone, documented
save/rename API was established in this investigation, and no such API was invoked.

This distinction matters: runtime persistence APIs provide automated shared-storage
coverage, but they do not replace Workbench component-save, rename, move and version
acceptance. Those gates remain open. The vendor example was inspected locally;
vendor source and machine-specific paths are not copied into the repository.
