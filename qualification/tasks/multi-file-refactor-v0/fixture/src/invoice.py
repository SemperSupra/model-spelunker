from src.config import DEFAULT_EXCHANGE_RATE
from src.currency import convert

def calculate_total_cents(items: list[int], rate: float = DEFAULT_EXCHANGE_RATE) -> int:
    subtotal = sum(items)
    return convert(subtotal, rate)
