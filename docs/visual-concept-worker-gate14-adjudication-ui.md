# Visual Concept Worker Gate 14 — Trusted-local adjudication UI

Gate 14 qualifies a loopback-only human surface over the Gate-13 adjudication
contract.

The page is intentionally a thin adapter. It does not own semantic rules,
candidate promotion, or gold creation.

## Local-only boundary

The server:

- binds to 127.0.0.1;
- generates a per-launch bearer token kept in the URL fragment/session storage;
- requires matching Host/Origin and token on API/media requests;
- sends no external scripts, fonts, telemetry, or network requests;
- rechecks image SHA-256 before serving bytes;
- verifies the benchmark SHA-256 against the completed blind session.

Do not forward or externally expose the port.

## Human workflow

For each asset the page shows:

- the original content-addressed image;
- the immutable blind-human first-pass record;
- seed reference evidence;
- automated evidence under pseudonymous source names;
- descriptive comparison cues.

Automated source identity is hidden until the reviewer explicitly presses the
reveal control. That reveal is appended to the adjudication ledger.

The reviewer can then append an adjudication event for either an explicit
canonical concept ID or a human statement. There is no automatic free-text to
concept mapping and no "accept model answer" operation.

## Authority

The UI writes only Gate-13 adjudication events. It exposes no endpoint for gold
promotion, accuracy scoring, candidate acceptance, or CPE mutation. Any future
gold layer requires a separate explicit workflow and authority decision.

The public ringer uses synthetic images, blind events, seed rows, and automated
observations. It checks loopback authentication, same-origin enforcement,
pseudonymous-source default, explicit source reveal, content-addressed image
serving, and adjudication writes without private content.
