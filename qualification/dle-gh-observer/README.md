# Git + GitHub CLI source-observation experiment

This is **not a new DLE engine, credential broker, WOW Sidecar operator, or accepted authority**. It is a read-only candidate under Model Spelunker qualification and governance DLE Continuity Bridge #227.

Use the installed official `git` and `gh` tools. Interactive users authenticate with `gh auth login` **outside** this experiment; GitHub Actions use the ephemeral read-only `GH_TOKEN`. Do not call `gh auth token`, copy `hosts.yml`, read the keychain directly, or store credentials.

Run:
```sh
go test ./... -count=1
go run . --repo SemperSupra/model-spelunker --issue 139 --checkout /path/to/checkout
```

The typed experiment calls only `git rev-parse --verify` and `gh api --method GET` for a repository, its default branch ref, and one named issue. It outputs source identities, body SHA-256, comment **count only**, local/remote revisions, and its evidence boundary. It does not emit the issue body, trust issue text as accepted semantics, fetch comment content, or mutate anything.

Important: the output is an **API observation**, not a GitHub-signed attestation or an atomic snapshot. The three API reads may observe different moments; the issue body is mutable; an issue timestamp and local body hash are not a compare-and-swap token. Missing comments, reviews, checks, branch/write permissions, local worktrees and owner decisions remain UNKNOWN. Existing governance `reconcile`, `projection` and Agent Dispatch own their own semantics. Keep this as a falsifiable benchmark probe until real-live admission proves value.
