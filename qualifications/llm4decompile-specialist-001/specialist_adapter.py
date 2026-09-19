#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import urllib.request

OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
SPECIALIST_MODEL = "llm4decompile"


def clean_objdump_main(disassembly: str) -> str:
    """Convert baseline Intel-syntax objdump output into the upstream prompt surface."""
    out: list[str] = []
    started = False
    for raw in str(disassembly).splitlines():
        line = raw.rstrip()
        if "<main>:" in line:
            started = True
            out.append("<main>:")
            continue
        if not started:
            continue
        if not line.strip():
            if len(out) > 1:
                break
            continue
        if "\t" in line:
            parts = line.split("\t")
            instruction = parts[-1].strip()
        else:
            m = re.match(r"^\s*[0-9a-fA-F]+:\s+(?:[0-9a-fA-F]{2}\s+)+(.*)$", line)
            instruction = m.group(1).strip() if m else line.strip()
        instruction = instruction.split("#", 1)[0].strip()
        if instruction:
            out.append(instruction)
    if len(out) < 2:
        raise RuntimeError("could not derive cleaned main assembly from objdump output")
    return "\n".join(out)


def build_prompt(disassembly: str) -> str:
    cleaned = clean_objdump_main(disassembly)
    return "# This is the assembly code:\n" + cleaned + "\n# What is the source code?\n"


def decompile_main(assembly: str) -> str:
    body = json.dumps({
        "model": SPECIALIST_MODEL,
        "prompt": build_prompt(assembly),
        "stream": False,
        "raw": True,
        "keep_alive": 0,
        "options": {
            "temperature": 0.0,
            "num_ctx": 4096,
            "num_predict": 1024
        }
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=900) as response:
        payload = json.load(response)
    text = str(payload.get("response", "")).strip()
    if not text:
        raise RuntimeError("LLM4Decompile returned an empty response")
    return text


def numeric_candidates(text: str, limit: int = 32) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()

    for token in re.findall(r"0x[0-9a-fA-F]+", str(text)):
        value = int(token, 16)
        if 0 <= value <= 999999 and value not in seen:
            seen.add(value)
            values.append(value)
            if len(values) >= limit:
                return values

    for token in re.findall(r"(?<![A-Za-z0-9_])(\d{3,6})(?![A-Za-z0-9_])", str(text)):
        value = int(token, 10)
        if 0 <= value <= 999999 and value not in seen:
            seen.add(value)
            values.append(value)
            if len(values) >= limit:
                break
    return values
