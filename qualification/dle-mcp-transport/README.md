# Read-only shared DLE MCP transport qualification (synthetic)

Owner: existing Model Spelunker qualification corpus, cross-referenced to the privately owned governance DLE Continuity Bridge #227 and Agent Dispatch #110.

This is **not production-ready**. It does not implement a new DLE database, copy private Go source, authenticate GitHub independently, or grant GitHub/DLE mutation. It exposes exactly two read-only tools over both stdio and Streamable HTTP using the official, version-pinned `github.com/modelcontextprotocol/go-sdk`:

- `dle_discover`: identifies the single pinned workset and capability limits.
- `dle_observe`: calls the same pre-existing read-only source-observation primitive used by the native CLI (or a visibly synthetic fixture). Returns source identity and false-attestation guards, not issue-body text.

`dle_reconcile` is **intentionally not offered** until an authenticated source-to-existing-reconciler adapter qualifies; advertising a mock as a real semantic service would violate the Way of Working.

## Examples (public-safe only)

```sh
go test ./... -count=1
go run . -mode fixture -transport stdio -repo o/r -issue 7
DLE_MCP_BEARER_TOKEN=replace-with-unique-ephemeral-random-secret \
  go run . -mode fixture -transport http -repo o/r -issue 7 -addr 127.0.0.1:8787
```

Actual issue observation requires building the independently qualified `qualification/dle-gh-observer` executable and starting the server with `-mode observer -observer-bin ABSOLUTE_PINNED_EXECUTABLE -checkout PINNED_CHECKOUT -repo OWNER/REPO -issue N`. Target selection is fixed at process start; chat clients cannot widen the repository selector. The observer inherits the execution account's existing `gh` authentication and does not extract tokens.

HTTP is loopback-only with an explicit ephemeral bearer secret for the synthetic experiment. **Do not publicly expose this HTTP endpoint**, including through a public tunnel. It is NOT a complete OAuth/OIDC implementation. Production web clients require a separately qualified external MCP OAuth resource-server gateway with per-client authorization and trusted GitHub source access, without weakening the least-authority constraints.

Qualification must demonstrate exact result parity across local subprocess stdio and localhost HTTP, denied missing/incorrect HTTP tokens, isolated client invocations, no write tools and no claim that a GitHub source observation equals semantic DLE acceptance.
