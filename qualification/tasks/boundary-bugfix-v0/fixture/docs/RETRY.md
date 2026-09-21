# Retry policy

`backoff_seconds(attempt, base=2, cap=30)` uses **1-based** attempt numbers.

- `attempt` must be a positive integer. Zero and negative attempts are invalid and must raise `ValueError`.
- Before capping, the delay is `base ** (attempt - 1)` seconds.
- The returned delay is capped at `cap` seconds.
- The public function signature and integer return type are stable.

Examples: attempt 1 with base 2 yields 1 second; attempt 2 yields 2 seconds; attempt 3 yields 4 seconds.
