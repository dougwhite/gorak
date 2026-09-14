# Native Workbench frame handoff

The generated [mockup](launch-score-mockup.png) is a design reference, not evidence
that Gorak's generated frame renders. The current frame was reported blank in two
manual checks. The owner offered to build the frame in Workbench; use that export
to diagnose the difference and certify subsequent readable-source edits.

Application: `launch_score`. Frame: `launch_panel`. Window title: `Launch Score`.
Put these controls directly on the top form:

| Name | Control | Configuration |
| --- | --- | --- |
| `capsule_count` | EntryField | Integer input, initial value 1 |
| `calculate_score` | ButtonField | TextLabel `Calculate score` |
| `score` | EntryField | Integer output, read-only to the user, initial value 0 |

Use simple text trims for the heading, Capsules label and Score label. Optional
subtitle: `10 points per capsule`; name that trim `points_caption` so the manual
12-point change can update its text. Approximately 520 × 380 pixels is ample;
exact spacing and fonts are not acceptance requirements.

Frame script:

```text
initialize() =
{
    capsule_count = 1;
    score = 0;
}
```

Button event:

```text
on click =
{
    score = CALLPROC p4_score(capsules = capsule_count);
}
```

The existing `p4_score` procedure implements `capsules * 10`. Save and compile,
then test 1 → 10 and 5 → 50. Close the frame/editor before Gorak exports or pushes.
Do not alter the test application or database tracking infrastructure while
building the layout. Local connection details remain outside this document.

Mockup generated with built-in ImageGen. Prompt: create a crisp, front-on, simple
native Windows desktop form titled Launch Score, light grey background, heading
Launch Score, subtitle 10 points per capsule, Capsules numeric input showing 5,
Calculate score button, divider, read-only Score numeric output showing 50, and
small Gorak / OpenROAD demo footer. Use ordinary native controls with comfortable
spacing, approximate proportions 520 × 380, and caption Proposed frame layout.
No charts, illustrations, web-browser chrome or extra buttons.
