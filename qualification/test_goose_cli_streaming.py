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

cache_dir = Path.home() / ".cache"
cache_dir.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory(prefix="goose-adapter-stream-test-", dir=str(cache_dir)) as temp:
    temp = Path(temp)
    if os.name == "nt":
        fake = temp / "fake-goose.cmd"
        fake.write_text(
            f'@"{sys.executable}" -c "import time; print(\'GOOSE_STREAM_MARKER=before-timeout\', flush=True); time.sleep(10)" %*\n',
            encoding="utf-8",
        )
    else:
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

    if os.name == "nt":
        arg_goose = temp / "arg-goose.cmd"
        arg_goose.write_text(
            f'@"{sys.executable}" -c "import json, sys; print(\'GOOSE_ARGV=\' + json.dumps(sys.argv[1:]), flush=True)" %*\n',
            encoding="utf-8",
        )
    else:
        arg_goose = temp / "arg-goose"
        arg_goose.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "print('GOOSE_ARGV=' + json.dumps(sys.argv[1:]), flush=True)\n",
            encoding="utf-8",
        )
        arg_goose.chmod(0o755)
    env["GOOSE_BIN"] = str(arg_goose)
    env["MODEL_SPELUNKER_MAX_ITERATIONS"] = "8"
    completed = subprocess.run(
        [sys.executable, str(ADAPTER)],
        input="check max turns\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
        check=True,
    )
    assert '"--max-turns", "8"' in completed.stdout, completed.stdout

    env["MODEL_SPELUNKER_MAX_ITERATIONS"] = "25"
    rejected = subprocess.run(
        [sys.executable, str(ADAPTER)],
        input="check invalid max turns\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
        check=False,
    )
    assert rejected.returncode == 2, rejected.returncode
    assert "between 1 and 24" in rejected.stderr, rejected.stderr

print("PASS Goose adapter exposes partial child output before timeout and honors bounded max iterations")
