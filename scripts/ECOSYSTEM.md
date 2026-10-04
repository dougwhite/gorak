# Merge-triggered ecosystem candidates

After a code/contract merge into `master` passes both CI platforms, gorak creates
an immutable development tag and GitHub prerelease, then opens or advances a
compatibility PR in each of the four consumers. Candidate creation needs no polling or manual
trigger. Documentation/branding-only changes skip propagation.

Tags use the package version and CI run number, for example
`v0.1.0-alpha.1.dev.42`. These are source snapshots of the tested merge: the package
version is unchanged and no wheel/executable is published by this job. They are
integration candidates, not final releases or updates for ordinary users.

Each PR proposes the candidate tag and its source contract, highlights contract
changes, and runs the consumer's existing CI. An open automation PR receives a
new pin commit on its existing branch, preserving human fixes. Conflicts or red
tests require adaptation. Closing that candidate's original PR declines it;
later candidates may create a new proposal. Only `ecosystem.toml` is changed.
The extension's language-server/designer pins remain their published releases
until their own release propagation is implemented.

Retries reuse the immutable candidate and existing PRs. Failures in one consumer
do not prevent attempts in the others; the root job still fails so incomplete
propagation is visible. Superseded root runs do not move downstream pins back.

## Credential setup

In gorak, add the Actions secret `ECOSYSTEM_PR_TOKEN`: a fine-grained personal
access token scoped to `gorak-lsp-rs`, `gorak-frame-designer`, `gorak-vscode-ext`
and `openroad_demo`, with **Contents: read and write** and **Pull requests: read
and write**. Choose an expiry and renew it before expiry. It does not need
Workflows, administration, or access to other repositories. Never commit it.
The built-in gorak token creates gorak candidate tags/prereleases; the separate
status workflow uses it to maintain tracking issues in gorak. The PAT
creates downstream branches/PRs so normal PR CI starts unattended.

A separate workflow starts after root push CI completes and maintains one active
ecosystem issue, advancing it to the latest published candidate and collecting
exact PR heads and downstream CI results
for up to twenty minutes. No daily schedule is used. Later checks can be refreshed
with its manual candidate input or during [coordinator review](COORDINATE.md).
Intermediate candidates do not require separate review or immediate fixes: work
on gorak for several merges, then ask Codex to bring the ecosystem up to speed.
Open downstream PRs advance in place rather than multiplying. Old status runs
cannot move the active issue backwards. After the owner closes a completed
coordination issue, a later candidate starts a new round; old retries leave the
closed issue alone. The managed status block preserves review findings and owner
notes outside it.
Review findings must be rechecked whenever their recorded PR heads change.

This first stage never automatically merges, releases consumers, or publishes a
final gorak release. Final release coordination must certify the complete
extension against the selected candidate before promoting final tags. That gate,
consumer-release propagation, binaries and self-updates are subsequent work.

## Dependency releases to the extension

Published language-server/designer releases notify **Dependency release updates**
in gorak. The coordinator verifies assets against SHA256SUMS, pins the LSP
release.json SHA256 or designer archive SHA512, and regenerates the designer npm
lock without lifecycle scripts. It advances the existing extension compatibility
PR atomically, retaining other dependency pins and human fixes. Installed-VSIX CI
certifies the new assets. No source merge in those repos sends a notification.

This uses the same active tracking issue. Changed dependency work may reopen a
completed issue for the same gorak candidate; an unchanged retry does not. Previous
merged extension PRs do not hide the current open dependency PR. Old release
notifications and attempted version regressions do not downgrade newer pins.

Set `ECOSYSTEM_DISPATCH_TOKEN` in the language-server and designer repos, scoped
only to gorak with Contents read/write, to send repository-dispatch notifications.
The root uses its existing `ECOSYSTEM_PR_TOKEN`; no additional extension secret or
PAT permissions are required. Merge the root coordinator before the sender changes.
The token does not need Issues, Pull requests, Actions, Workflows or administration.

After failed notification delivery, rerun the sender's **Notify ecosystem of
dependency release** workflow with the published tag. After receiver failure,
rerun **Dependency release updates** in gorak with source repo and tag. These
retries reuse commits/PRs and never need republishing or moving release tags.
