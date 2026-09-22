# Visual Concept Worker Gate 13 — Post-blind adjudication contract

Gate 13 qualifies the mechanics needed after an independent blind human pass has
already completed.

The contract keeps five layers distinct:

1. seed reference;
2. automated candidate observations;
3. immutable blind-human first-pass events;
4. append-only adjudication events;
5. any future gold layer.

Gate 13 implements layers 1–4 only. It has no gold promotion or candidate
acceptance operation.

## Input binding

An adjudication session fails closed unless:

- the blind session contains a non-empty content-addressed asset set;
- the blind human ledger hash chain is intact;
- every asset has exactly one blind first-pass event;
- no first-pass event is already marked exposed to reconciliation;
- the reconciliation queue digest is intact;
- the queue asset set and SHA-256 identities exactly match the blind session.

The adjudication session then binds the blind-session digest/SHA-256, blind-ledger
SHA-256 and tail event digest, reconciliation-queue digest/SHA-256, ordered asset
identities, reviewer, and implementation revision.

## Bias control

Automated sources are pseudonymized as source-A/source-B/... by default. A human
may explicitly reveal source identities for an asset; that reveal is itself an
append-only adjudication event. There is no "accept model answer" shortcut.

## Adjudication events

An adjudication event records an explicit human decision about either a canonical
concept ID or a human statement. The implementation does not fuzzy-map free text
to concept IDs and does not ask a model to infer semantic equivalence.

Allowed decisions are:

- supported;
- contradicted;
- unknown;
- abstain;
- needs_followup.

Events carry idempotency keys and fail closed if one key is reused for a different
decision. They remain layer=adjudication, ground_truth=false, gold=false.

## Public ringer

The Gate-13 ringer uses synthetic sessions, human events, and automated evidence.
It challenges incomplete/tampered blind ledgers, asset substitution, source-name
leakage before reveal, duplicate/replayed adjudication, unsupported auto-mapping
subject types, and attempts to inject ground-truth authority.

Private media, private benchmark results, and private human judgments are absent.
