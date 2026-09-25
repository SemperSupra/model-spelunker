def backoff_seconds(attempt: int, base: int = 2, cap: int = 30) -> int:
    """Return the bounded exponential retry delay in seconds."""
    if attempt < 0:
        raise ValueError("attempt must not be negative")
    return min(cap, base ** attempt)
