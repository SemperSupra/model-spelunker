# Retry policy

- Attempts are numbered starting at 1.
- For attempt N, the uncapped delay is `base ** (N - 1)` seconds.
- Return the smaller of that delay and `cap`.
- A non-positive attempt is invalid and must raise `ValueError`.
- Preserve the existing function signature and integer return type.
