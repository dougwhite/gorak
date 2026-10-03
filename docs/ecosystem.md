# Ecosystem compatibility

`ecosystem.toml` records repositories, contract consumers, bundled products and
copied assets. It describes development dependencies, not a tested release bundle
and not a claim that downstream repositories already support a contract version.

The current readable source and native stylesheet contracts start at version 1.
These numbers are independent of component release versions. They label the current
explicit WML/named stylesheet format; they do not provide migration from retired formats.

For a public contract change:

1. Update the format documentation and compatibility fixtures/tests.
2. Increment each affected contract version when accepted source, its interpretation,
   emitted representation or stock baseline changes in a way consumers must handle.
   Internal fixes that restore documented behaviour do not require a bump.
3. Identify consumers and copied assets from `ecosystem.toml`. Describe downstream
   work in the PR; prepare compatibility PRs when authorized. Do not update satellite
   default branches directly or claim compatibility before consumer tests pass.
4. Consumers record a supported contract version and pin the fixture/asset revision.
   Accepting a pin update requires their own behavioural checks, not just root CI.

Additive changes can also affect consumers; review them explicitly. Keep downstream
development pinned while compatibility updates are being prepared. No automatic
cross-repository writes or release coordination is implemented by this manifest.

The extension currently bundles the LSP; designer integration is planned. Their
host interfaces remain unversioned until documented and tested. The designer stock
stylesheet is copied from Gorak with a path-removal transformation; the editor JSON
schema currently belongs to the extension. Both need reproducible asset checks in
their consumer repositories.

Later ecosystem releases should pin exact component tags/commits and verified
artifacts in a separate release manifest. The CLI updater and Marketplace extension
updates are distribution concerns and do not define source compatibility.
