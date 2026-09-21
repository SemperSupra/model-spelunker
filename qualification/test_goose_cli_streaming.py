#!/usr/bin/env python3
"""Regression: Goose adapter must expose partial child output before timeout."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "qualification" / "adapters" / "goose_cli.py"

with tempfile.TemporaryDirectory(prefix="goose-adapter-stream-test-") as temp:
    temp = Path(temp)
    fake = temp / "fake-goose"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "print('GOOSE_STREAM_MARKER=before-timeout', flush=True)\n"
        "time.sleep(10)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    env = dict(os.environ)
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OLLAMA_API_KEY",
    ):
        env.pop(key, None)
    env.update(
        {
            "GOOSE_BIN": str(fake),
            "MODEL_SPELUNKER_MODEL": "qwen3:1.7b",
            "GOOSE_OLLAMA_HOST": "http://127.0.0.1:11434",
            "GOOSE_XDG_CONFIG_HOME": str(temp / "config"),
            "GOOSE_XDG_DATA_HOME": str(temp / "data"),
        }
    )

    try:
        subprocess.run(
            [sys.executable, str(ADAPTER)],
            input="exercise streaming\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=0.75,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        assert "GOOSE_STREAM_MARKER=before-timeout" in stdout, stdout
    else:
        raise AssertionError("fake Goose unexpectedly exited before timeout")

print("PASS Goose adapter exposes partial child output before timeout")
