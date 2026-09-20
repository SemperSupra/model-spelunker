# Validation policy

The canonical local validation entrypoint for a code change is:

`python scripts/validate.py`

This runs the repository's substantive checks. `scripts/quick_check.sh` is only a convenience syntax check and must not be treated as equivalent validation.
