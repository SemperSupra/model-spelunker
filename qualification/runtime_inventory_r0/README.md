# Offline Ollama inventory qualification oracle — R0

Issue: [SemperSupra/model-spelunker#299](https://github.com/SemperSupra/model-spelunker/issues/299). Real private host observer owner: [IaC #667](https://github.com/mark-e-deyoung/infrastructure-as-code-private/issues/667). This is an independent synthetic behavior fixture, not a model registry, telemetry service, runtime driver, agent router, permission system, or host probe.

**No network code exists in this Go package.** Callers provide two JSON samples and observation timestamps. `/api/tags` describes model aliases and provider-reported manifest metadata; `/api/ps` describes loaded models. Neither is proof of actual request activity, GPU VRAM residency, installed byte authenticity, immutable MAF OCI identity, or Model Spelunker task qualification. The provider-reported digest is kept in its own namespace and **never** promoted to OCI, GGUF file hash or Foundry approval.

The deterministic output distinguishes advertised/present-but-not-loaded, loaded-with-activity-unknown, running-but-unlisted, and conflicting same-alias manifest metadata. Entry `Activity` remains `UNKNOWN`, `RegisteredIdentity` `UNVERIFIED`, and `Approval` `UNKNOWN`. Zero models is a valid observed state, but absent or stale lists are errors. Each model name must be safe, unambiguous and unique; JSON duplicate keys anywhere are rejected. Observation JSON size is capped at 2MiB; actor/runtime evidence freshness is bounded by caller-supplied `MaxAge` and `Now`.

`GOPROXY=off GOSUMDB=off go test -count=3 ./...` and `go vet ./...` are test commands. Only synthetic fixture inputs, no private model names/endpoints/secrets/weights. Public free GHA is the execution plane. The actual site collector must independently authenticate endpoint access, bind route to worker process generation, use protected transport, and publish a redacted *private* receipt. The static schema does not establish live HIL or authorization for backend changes.

This intentionally does **not** parse llama.cpp/llama-swap/Strata yet. The private host census will require separate source-inspected adapters rather than pretending Ollama's API describes all backends.
