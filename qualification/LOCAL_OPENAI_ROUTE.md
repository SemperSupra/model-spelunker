# Explicit local OpenAI-compatible actor treatment

Owner: configured-actor qualification issue #139. This is a **proposed source-level transport treatment** for the existing OpenWorker projected harness. It does not admit an actor, change a runner, grant write authority or prescribe a new execution system.

## Contract

To select this treatment, the caller must set all applicable values in its **private execution environment**:

- MODEL_SPELUNKER_MODEL=local-openai:<exact model ID>
- MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL=<approved existing private or loopback OpenAI-compatible URL ending in /v1>
- MODEL_SPELUNKER_LOCAL_OPENAI_API_KEY=<optional credential from approved secret store; mandatory HTTPS when present>

The only addition to existing adapter execution is an explicit OpenAIProvider(api_key=..., base_url=...) instance with the exact bare model ID. The absence of an endpoint/model fails closed. Unqualified/default `openai:` and bare model values **do not** become local treatments. A placeholder client key is used for no-auth local model endpoints, never an upstream API key.

Before constructing the provider, the resolver checks URL syntax, absence of embedded credentials/query/fragment, exact /v1 path, all observed DNS/IP answers belonging to loopback/RFC1918/CGNAT/IPv6 ULA and credential-bearing HTTPS. It also refuses nonempty inherited HTTP_PROXY, HTTPS_PROXY, or ALL_PROXY variables (case-insensitive), since the pinned OpenWorker OpenAI SDK client inherits ambient HTTPX proxy configuration by default. Configure an admitted direct route; do not silently proxy a private inference request. The resolver never writes host identifiers, credential values or request content into GitHub artifacts or error strings.

**Important limits:** DNS-time checks are not a firewall or defense against later DNS rebinding. A hostile actor/library with arbitrary shell and network capability remains outside this guard; use an admitted bounded workcell and private egress ACL. Proxy behavior, certificate trust and actual wire-tool compatibility require runtime verification. Model Spelunker remains responsible for external task validation and independent receipts.

## Qualification protocol

1. Offline: run `python3 -m unittest discover -s qualification/tests -p 'test_local_openai_route.py' -v`.
2. Under the owning private local runner/workcell, verify the route against observed /v1/models before any agent task; this is a different gate owned by the execution controller.
3. For the first task, reuse the existing pinned OpenWorker Linux/x64 artifact, existing `qualification/run_task.py`, `qualification/adapters/openworker_projected.py`, `qualification/tasks/text-repair-v0` and external oracle, with a bounded tool projection and exactly one selected local-model endpoint.
4. Record endpoint *identity by private authority reference/digest*, model ID/artifact version, current harness digest, task source, tool projection, timeout, independent verifier and output receipt; do not disclose host/path/credential values.
5. No admission until a real task succeeds and a separate independent verifier accepts it. Route reachability or a synthetic function-call response is not task qualification.

This treatment does not install weights, create listeners, expose a private machine publicly, alter any model router, enable autonomous mutation, or override an operator's existing holds.
