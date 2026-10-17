#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import inspect
import sys
import tempfile
from pathlib import Path

ORIGINAL_CONFIG = """# Frozen configuration - do not modify
DEFAULT_EXCHANGE_RATE = 1.25
BASE_CURRENCY = "USD"
TARGET_CURRENCY = "EUR"
"""

def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(root: Path) -> bool:
    try:
        # 1. Config immutability check
        config_path = root / "src" / "config.py"
        if not config_path.is_file() or config_path.read_text(encoding="utf-8") != ORIGINAL_CONFIG:
            return False

        # 2. Check no rogue files
        for p in root.rglob("*"):
            if p.is_file() and p.suffix == ".py":
                rel = p.relative_to(root).as_posix()
                if rel not in {"src/config.py", "src/currency.py", "src/invoice.py"}:
                    return False

        # Need to insert root into sys.path temporarily so `from src...` imports work
        old_path = list(sys.path)
        sys.path.insert(0, str(root))
        try:
            # 3. Test currency.py
            curr_mod = load_module(root / "src" / "currency.py", "test_currency")
            fn_convert = getattr(curr_mod, "convert_currency", None)
            if fn_convert is None:
                return False

            cases_currency = [
                ((100, 1.25), 125),
                ((100, 1.006), 101),
                ((100, 1.004), 100),
                ((0, 1.5), 0),
                ((250, 0.5), 125),
                ((333, 1.333), 444),
            ]
            for (amt, rate), expected in cases_currency:
                val = fn_convert(amt, rate)
                if not isinstance(val, int) or val != expected:
                    return False

            # 4. Test invoice.py
            inv_mod = load_module(root / "src" / "invoice.py", "test_invoice")
            fn_total = getattr(inv_mod, "calculate_total_cents", None)
            if fn_total is None:
                return False

            cases_invoice = [
                (([100, 200, 300], 1.25), 750),
                (([50, 50], 1.0), 100),
                (([100],), 125),
                (([],), 0),
            ]
            for args, expected in cases_invoice:
                val = fn_total(*args)
                if not isinstance(val, int) or val != expected:
                    return False

            return True
        finally:
            sys.path = old_path
    except Exception:
        return False


def self_test() -> int:
    good_currency = """def convert_currency(amount_cents: int, exchange_rate: float) -> int:
    return int(round(amount_cents * exchange_rate))
"""
    good_invoice = """from src.config import DEFAULT_EXCHANGE_RATE
from src.currency import convert_currency

def calculate_total_cents(items: list[int], rate: float = DEFAULT_EXCHANGE_RATE) -> int:
    subtotal = sum(items)
    return convert_currency(subtotal, rate)
"""
    bad_currency_no_round = """def convert_currency(amount_cents: int, exchange_rate: float) -> int:
    return int(amount_cents * exchange_rate)
"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir(parents=True)
        (root / "src" / "config.py").write_text(ORIGINAL_CONFIG, encoding="utf-8")

        # Good both files
        (root / "src" / "currency.py").write_text(good_currency, encoding="utf-8")
        (root / "src" / "invoice.py").write_text(good_invoice, encoding="utf-8")
        assert check(root)

        # Truncation rounding fails
        (root / "src" / "currency.py").write_text(bad_currency_no_round, encoding="utf-8")
        assert not check(root)
        (root / "src" / "currency.py").write_text(good_currency, encoding="utf-8")

        # Broken invoice (still importing old convert) fails
        broken_invoice = """from src.currency import convert
def calculate_total_cents(items, rate=1.25): return convert(sum(items), rate)
"""
        (root / "src" / "invoice.py").write_text(broken_invoice, encoding="utf-8")
        assert not check(root)

        # Modified config fails
        (root / "src" / "invoice.py").write_text(good_invoice, encoding="utf-8")
        (root / "src" / "config.py").write_text("DEFAULT_EXCHANGE_RATE = 2.0\n", encoding="utf-8")
        assert not check(root)

    print("PASS multi-file-refactor verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(0 if check(Path(sys.argv[1])) else 1)
