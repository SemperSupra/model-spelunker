def convert(amount, rate):
    # Legacy conversion: truncates instead of rounding to nearest cent
    return int(amount * rate)
