#!/usr/bin/env python3
from __future__ import annotations
import json, re, urllib.request

OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
SPECIALIST_MODEL = "rtlcoder:q4_0"

def _extract_rtl(text: str) -> str:
    text = str(text or "").strip()
    fenced = re.search(r"```(?:systemverilog|verilog|sv)?\s*(.*?)```", text, re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = re.search(r"\bmodule\b", text)
    if start:
        text = text[start.start():]
    end = text.find("endmodule")
    if end >= 0:
        text = text[: end + len("endmodule")]
    return text.strip() + "\n"

def generate_verilog(spec: str) -> str:
    prompt = (
        "Please act as a professional verilog designer.\n"
        "Implement the following bounded RTL task. Return only a complete "
        "synthesizable Verilog/SystemVerilog module; do not include explanation.\n\n"
        + str(spec).strip() + "\n"
    )
    body = json.dumps({
        "model": SPECIALIST_MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": 0,
        "options": {"temperature": 0.0, "num_ctx": 4096, "num_predict": 1024},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_GENERATE_URL, data=body,
        headers={"Content-Type":"application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=900) as response:
        payload = json.load(response)
    rtl = _extract_rtl(payload.get("response",""))
    if "module" not in rtl or "endmodule" not in rtl:
        raise RuntimeError("RTLCoder response did not contain a complete module")
    return rtl
