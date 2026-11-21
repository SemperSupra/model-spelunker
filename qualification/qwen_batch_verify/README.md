# Public-source GitHub run attestation — R6-A

Owner: [Model Spelunker #234](https://github.com/SemperSupra/model-spelunker/issues/234), child of [batch #224](https://github.com/SemperSupra/model-spelunker/issues/224). Source base: [batch PR #225](https://github.com/SemperSupra/model-spelunker/pull/225). This is a **pure, bounded, read-only verifier** and not an executor, independent reviewer of model semantics, credential broker, or admission grant.

The source-bound packet ledger already pins four `DONE_VERIFIED` and two `FAILED` public-safe test outcomes. Previously its validator checked only SHA syntax, run-link form and internally written `PASS/FAIL` declarations; an actor could invent a plausible run link. This adds an **external status and job witness** using exact REST endpoints on the one public repository `SemperSupra/model-spelunker` and a separate reviewed source/workflow/job pin file. It refuses an unexpected GitHub host/path, duplicate/missing jobs, incomplete REST pages, stale commit SHAs, wrong run and job conclusion, fabricated false-success and an unknown evidence packet.

The independent CI runs two parallel public jobs: an offline positive/negative/forge suite with no network, and the live GitHub REST status verifier with **twelve or fewer bounded read-only public GETs** and no token or personal/private GitHub authorization. It emits a bounded public run/job status receipt but **does not authenticate semantic assertions inside CI logs/artifacts**, actual private guest access, VM effects, model inference, local data or signed admission. A GitHub API rate-limit/timeout causes FAIL_CLOSED rather than passing a stale status. Files from the private IaC repository are never transmitted to public CI.

From a public checkout:

```sh
python3 -m unittest discover -s qualification/qwen_batch_verify -p test_verify.py -v
python3 qualification/qwen_batch_verify/verify.py
```

The second command uses the network only to the exact allowlisted public GitHub repository. An actor should not run it on a private repository without a separately reviewed source classification. Do not include credentials in the returned evidence, elevate the actor, merge on green alone, or infer that a green status is a product release approval.

No host effect. No changes to #225’s ledger/contract files. Distinct files and PR. DLE and owner acceptance remain external.
