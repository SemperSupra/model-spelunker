# Read-only shared DLE MCP transport qualification (synthetic)

Owner: existing Model Spelunker qualification corpus, cross-referenced to the privately owned governance DLE Continuity Bridge #227 and Agent Dispatch #110.

This is **not production-ready**. It does not implement a new DLE database, copy private Go source, authenticate GitHub independently, or grant GitHub/DLE mutation. By default it exposes exactly two read-only tools over both stdio and Streamable HTTP using the official, version-pinned `github.com/modelcontextprotocol/go-sdk`:

- `dle_discover`: identifies the single pinned workset and capability limits.
- `dle_observe`: calls the same pre-existing read-only source-observation primitive used by the native CLI (or a visibly synthetic fixture). Returns source identity and false-attestation guards, not issue-body text.

An optional third `dle_reconcile` tool is registered **only** when the instance is explicitly configured with the existing qualified **external** Go reconciler binary, its exact SHA256, an exact SHA256-pinned independently selected local DLE JSON snapshot, and a fixed untrusted candidate JSON. This adapter freezes source/executable copies into a private temporary directory, invokes only the frozen binary without a shell, checks the reconciler's own result and context hashes/acceptance grade, and returns only aggregate candidate-disposition counts and source/binary digests. It does **not** expose candidate text or accepted-claim bodies and it cannot alter the GitHub issue. No caller-selected repo, file path, or command is accepted.

The public tests use an invented **synthetic reconciler executable**, not the private governance reconciler source. They qualify transport parity, subprocess invocation, input freezing, falsified receipt rejection, and denial behavior. They do **not** establish correct semantics of the private reconciler or independently authenticated GitHub ownership. Production `dle_reconcile` must be admitted privately under DLE Continuity Bridge #227.

## Examples (public-safe only)

```sh
go test ./... -count=1
go run . -mode fixture -transport stdio -repo o/r -issue 7
DLE_MCP_BEARER_TOKEN=replace-with-unique-ephemeral-random-secret \
  go run . -mode fixture -transport http -repo o/r -issue 7 -addr 127.0.0.1:8787
```

Actual issue observation requires building the independently qualified `qualification/dle-gh-observer` executable and starting the server with `-mode observer -observer-bin ABSOLUTE_PINNED_EXECUTABLE -checkout PINNED_CHECKOUT -repo OWNER/REPO -issue N`. Target selection is fixed at process start; chat clients cannot widen the repository selector. The observer inherits the execution account's existing `gh` authentication and does not extract tokens.

HTTP is loopback-only with an explicit ephemeral bearer secret for the synthetic experiment. **Do not publicly expose this HTTP endpoint**, including through a public tunnel. It is NOT a complete OAuth/OIDC implementation. Production web clients require a separately qualified external MCP OAuth resource-server gateway with per-client authorization and trusted GitHub source access, without weakening the least-authority constraints.


## Optional pinned local reconciliation (not remote GitHub authority)

```sh
# Build and qualify the existing governance Go reconciler in authorized private custody.
# Then configure the MCP adapter using already independently sourced private files.
# The `SHA256` inputs are source-integrity pins, not GitHub attestations.
# All five flags are required together; an omitted flag is a hard error.
go run . -transport stdio -mode observer \\
  -repo OWNER/REPO -issue 7 -observer-bin ABSOLUTE_OBSERVER \\
  -checkout ABSOLUTE_CHECKOUT \\
  -reconcile-bin ABSOLUTE_QUALIFIED_GO_RECONCILER \\
  -reconcile-bin-sha256 EXACT_BINARY_SHA256 \\
  -candidates ABSOLUTE_SELECTED_CANDIDATES_JSON \\
  -dle ABSOLUTE_PINNED_DLE_JSON -dle-sha256 EXACT_DLE_SHA256
```

No runtime in this repository automatically acquires private GitHub issues or their semantic decisions. Fetch through a separately admitted owner-bound GitHub source adapter, preserve current issue/revision, and ensure results are candidate-only. On uncertain provenance or stale authority, STOP. Never deploy this synthetic loopback bearer as a public MCP resource server.

Qualification must demonstrate exact result parity across local subprocess stdio and localhost HTTP, denied missing/incorrect HTTP tokens, isolated client invocations, no write tools and no claim that a GitHub source observation equals semantic DLE acceptance.
