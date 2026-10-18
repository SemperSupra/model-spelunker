#!/usr/bin/env python3
"""Independent semantic oracle: parses bounded JSON AST, not actor Python code.

Isolation requirement: this script plus manifest/source must be inaccessible to
the candidate workcell at the OS/container permission layer.
"""
from __future__ import annotations
import copy
import hashlib
import json
import random
import sys
import tempfile
from pathlib import Path

P = Path(__file__).resolve().parent
MASK = 0xFFFFFFFF
OPS = {"add", "mul", "xor"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def eval_expr(node: object, value: int, depth: int = 0, budget: list[int] | None = None) -> int:
    if budget is None:
        budget = [0]
    budget[0] += 1
    if budget[0] > 128 or depth > 32 or not isinstance(node, dict):
        raise ValueError("expression budget / depth / type exceeded")
    op = node.get("op")
    if op == "input" and set(node) == {"op"}:
        return value & MASK
    if op == "const" and set(node) == {"op", "value"} and type(node["value"]) is int and 0 <= node["value"] <= MASK:
        return node["value"]
    if op in OPS and set(node) == {"op", "args"} and isinstance(node["args"], list) and len(node["args"]) == 2:
        left = eval_expr(node["args"][0], value, depth + 1, budget)
        right = eval_expr(node["args"][1], value, depth + 1, budget)
        return {"add": lambda: (left + right) & MASK, "mul": lambda: (left * right) & MASK, "xor": lambda: left ^ right}[op]()
    if op == "rol" and set(node) == {"op", "arg", "bits"} and type(node.get("bits")) is int and 0 <= node["bits"] < 32:
        x = eval_expr(node["arg"], value, depth + 1, budget)
        bits = node["bits"]
        return ((x << bits) | (x >> ((32 - bits) & 31))) & MASK
    raise ValueError("disallowed expression node")


def expected(command: int, value: int) -> int:
    value &= MASK
    if command == 17:
        return ((((value * 33) & MASK) ^ 0x5A5A5A5A) + 17) & MASK
    if command == 41:
        return (((value << 7) | (value >> 25)) ^ 0xA55A0FF0) & MASK
    if command == 61:
        x = 0x7F4A7C15
        for i in range(4):
            x = (((x << 3) | (x >> 29)) ^ ((value + i * 17) & MASK)) & MASK
        return x
    return MASK


def validate(candidate: Path) -> bool:
    try:
        manifest = json.loads((P / "oracle_manifest.json").read_text(encoding="utf-8"))
        for name in ("target.bin", "disassembly.txt"):
            if sha256((candidate / name).read_bytes()) != manifest["sha256"][name]:
                return False
        allowed = {"target.bin", "disassembly.txt", "recovered.json"}
        observed_files = {p.relative_to(candidate).as_posix() for p in candidate.rglob("*") if p.is_file() or p.is_symlink()}
        if observed_files != allowed or any((candidate / name).is_symlink() for name in allowed):
            return False
        answer = json.loads((candidate / "recovered.json").read_text(encoding="utf-8"))
        if set(answer) != {"schema_version", "width", "commands", "default"}:
            return False
        if type(answer["schema_version"]) is not int or answer["schema_version"] != 1 or type(answer["width"]) is not int or answer["width"] != 32:
            return False
        if not isinstance(answer["commands"], dict) or set(answer["commands"]) != {"17", "41", "61"}:
            return False
        r = random.Random(0xA11CE2026)
        inputs = [0, 1, 2, 3, 17, 0x12345678, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF]
        inputs.extend(r.getrandbits(32) for _ in range(71))
        for command, expr in [(17, answer["commands"]["17"]), (41, answer["commands"]["41"]), (61, answer["commands"]["61"]), (255, answer["default"])]:
            for value in inputs:
                if eval_expr(expr, value) != expected(command, value):
                    return False
        return True
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, OverflowError, RecursionError):
        return False


def correct_answer() -> dict:
    def c(v: int) -> dict: return {"op": "const", "value": v}
    def v() -> dict: return {"op": "input"}
    def b(op: str, x: dict, y: dict) -> dict: return {"op": op, "args": [x, y]}
    def rol(x: dict, n: int) -> dict: return {"op": "rol", "arg": x, "bits": n}
    fold = c(0x7F4A7C15)
    for i in range(4):
        fold = b("xor", rol(fold, 3), b("add", v(), c(i * 17)))
    return {"schema_version": 1, "width": 32, "commands": {
        "17": b("add", b("xor", b("mul", v(), c(33)), c(0x5A5A5A5A)), c(17)),
        "41": b("xor", rol(v(), 7), c(0xA55A0FF0)),
        "61": fold
    }, "default": c(MASK)}


def self_test() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d)
        if not (P / "oracle_manifest.json").is_file():
            print("SKIP: work sample not materialized; use prepare_work_sample.py")
            raise SystemExit(77)
        for name in ("target.bin", "disassembly.txt"):
            (path / name).write_bytes((P / "fixture" / name).read_bytes())
        def write(obj: dict) -> None:
            (path / "recovered.json").write_text(json.dumps(obj), encoding="utf-8")
        answer = correct_answer()
        write(answer)
        assert validate(path), "known-good rejected"
        bad = copy.deepcopy(answer); bad["commands"]["17"]["args"][1]["value"] = 18
        write(bad); assert not validate(path), "affine error accepted"
        bad = copy.deepcopy(answer); bad["commands"]["41"]["args"][0]["bits"] = 8
        write(bad); assert not validate(path), "rotation error accepted"
        bad = copy.deepcopy(answer); bad["commands"]["61"] = {"op": "const", "value": 0}
        write(bad); assert not validate(path), "fold error accepted"
        bad = copy.deepcopy(answer); bad["commands"]["17"] = {"op": "eval", "python": "1+1"}
        write(bad); assert not validate(path), "execution node accepted"
        bad = copy.deepcopy(answer); bad["commands"]["41"]["args"][0]["bits"] = True
        write(bad); assert not validate(path), "boolean-as-int accepted"
        write(answer)
        with (path / "target.bin").open("ab") as f:
            f.write(b"change")
        assert not validate(path), "binary mutation accepted"
        (path / "target.bin").write_bytes((P / "fixture" / "target.bin").read_bytes())
        (path / "unexpected.txt").write_text("bad", encoding="utf-8")
        assert not validate(path), "undeclared output accepted"
        (path / "unexpected.txt").unlink()
        (path / "target.bin").unlink()
        (path / "target.bin").symlink_to(P / "fixture" / "target.bin")
        assert not validate(path), "symlinked fixture accepted"
    print("PASS portable-dispatch semantics: known-good + eight negative controls, 320 held-out vectors")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        self_test()
    elif len(sys.argv) == 2:
        raise SystemExit(0 if validate(Path(sys.argv[1])) else 1)
    else:
        raise SystemExit("Usage: verify.py <candidate> | --self-test")
