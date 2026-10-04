# Merge-triggered ecosystem candidates

After a code/contract merge into `master` passes both CI platforms, gorak creates
an immutable development tag and GitHub prerelease, then opens or advances a
compatibility PR in each of the four consumers. There is no polling or manual
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
The built-in gorak token creates only gorak candidate tags/prereleases. The PAT
creates downstream branches/PRs so normal PR CI starts unattended.

This first stage never automatically merges, releases consumers, or publishes a
final gorak release. Final release coordination must certify the complete
extension against the selected candidate before promoting final tags. That gate,
consumer-release propagation, binaries and self-updates are subsequent work.
