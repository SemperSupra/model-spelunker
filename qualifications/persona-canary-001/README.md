# Persona qualification canary 001

This is the smallest whole-persona qualification proof.

It does not create a new scheduler, catalog, persona service, or benchmark platform. The existing Model Spelunker evidence contract supplies the plan/evidence binding; Agent Dispatch supplies the public CPU execution plane.

## What is being tested

Two complete persona realizations are sealed into `qualification.json`:

- an RTL engineer using a bounded write/test tool surface;
- a benign binary reverse-engineer using read-only static-analysis tools plus a single bounded verification oracle.

Both use the same small local controller so the first canary exercises persona configuration without multiplying model downloads. Each matched persona/workload pairing runs twice.

The scientific canary passes when each pairing succeeds at least once. A clean execution that does not meet that condition is still retained as negative evidence.

## Deliberate limits

- CPU-only.
- No external model API.
- No arbitrary shell tool is exposed to either persona.
- No malware or third-party binary corpus: the reverse-engineering fixture is compiled locally from benign source and the source is removed before the agent runs.
- No specialist model yet.
- No cross-product framework/model sweep yet.
- No new qualification schema: `qualification.json` is the sealed plan record for this bounded canary.

If this canary demonstrates useful, repeatable behavior, the next increment can justify admitting the controller artifact into Model Artifact Foundry and adding one challenger realization. If it does not, expand nothing; diagnose the failure first.

## Build for Agent Dispatch

```bash
python3 tools/build_sealed_capsule.py qualifications/persona-canary-001 --out .capsule/persona-canary-001
```

After sealed execution and trusted decryption:

```bash
python3 tools/check_plan_execution.py \
  .capsule/persona-canary-001/capsule-manifest.json \
  <decrypted-result-root>
```
