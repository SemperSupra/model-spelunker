#!/usr/bin/env bash
set -euo pipefail

: "${SEALED_RESULT_DIR:?SEALED_RESULT_DIR is required by Agent Dispatch sealed execution}"

python3 -m pip install --disable-pip-version-check --no-input \
  "pillow==12.3.0" \
  "transformers==5.16.1" \
  "torch==2.14.0"

export HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
export STUDY_JSON="$PWD/study.json"
export RESULT_JSON="$SEALED_RESULT_DIR/result.json"

python3 run_reproduction.py
cp study.json "$SEALED_RESULT_DIR/study.json"

python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path


def identity(path: Path) -> dict[str, object]:
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


out = Path(os.environ["SEALED_RESULT_DIR"])
receipt = {
    "schema_version": 1,
    "record_type": "execution-receipt",
    "inputs": {
        name: identity(Path(name))
        for name in ("study.json", "run.sh", "run_reproduction.py")
    },
    "outputs": {
        name: identity(out / name)
        for name in ("study.json", "result.json")
    },
}
(out / "execution-receipt.json").write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
