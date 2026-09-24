#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unicodedata
from pathlib import Path

EXPECTED = {
    "schema_version": 1,
    "source_locale": "en-US",
    "target_locale": "de-DE",
    "translations": [
        {"id": "s1", "text": "Knoten AX7 hat 14 von 21 Datensätzen verarbeitet."},
        {
            "id": "s2",
            "text": "Der Status bleibt UNKNOWN, weil die Prüfsumme QZ-42 nicht übereinstimmte.",
        },
        {"id": "s3", "text": "JOB-7 nicht vor 08:30 UTC erneut versuchen."},
        {
            "id": "s4",
            "text": "Build 2026.09.24 hat 3 von 5 Prüfungen abgeschlossen.",
        },
    ],
}

PROTECTED = [
    "AX7",
    "UNKNOWN",
    "QZ-42",
    "JOB-7",
    "08:30 UTC",
    "Build",
    "2026.09.24",
    "14",
    "21",
    "3",
    "5",
]


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def check(root: Path) -> tuple[bool, str]:
    path = root / "translation.json"
    if not path.is_file():
        return False, "missing-output"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, "invalid-json"

    if not isinstance(value, dict) or set(value) != set(EXPECTED):
        return False, "top-level-schema"
    if value.get("schema_version") != 1:
        return False, "schema-version"
    if value.get("source_locale") != "en-US" or value.get("target_locale") != "de-DE":
        return False, "locale"
    rows = value.get("translations")
    if not isinstance(rows, list) or len(rows) != 4:
        return False, "translation-count"

    actual_texts = []
    for index, (row, expected) in enumerate(zip(rows, EXPECTED["translations"])):
        if not isinstance(row, dict) or set(row) != {"id", "text"}:
            return False, f"row-schema:{index}"
        if row.get("id") != expected["id"] or not isinstance(row.get("text"), str):
            return False, f"row-id-or-text:{index}"
        actual = normalize_text(row["text"])
        wanted = normalize_text(expected["text"])
        if actual != wanted:
            return False, f"reference-mismatch:{expected['id']}"
        actual_texts.append(actual)

    joined = "\n".join(actual_texts)
    for token in PROTECTED:
        if token not in joined:
            return False, f"protected-token:{token}"

    return True, "pass"


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "translation.json").write_text(
            json.dumps(EXPECTED, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        ok, reason = check(root)
        assert ok, reason

        broken = json.loads(json.dumps(EXPECTED, ensure_ascii=False))
        broken["translations"][1]["text"] = broken["translations"][1]["text"].replace(
            "QZ-42", "QZ42"
        )
        (root / "translation.json").write_text(
            json.dumps(broken, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        ok, _ = check(root)
        assert not ok
    print("PASS translation-controlled-en-de-v2 verifier self-test")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    ok, reason = check(Path(sys.argv[1]))
    print(json.dumps({"ok": ok, "reason": reason}, sort_keys=True))
    raise SystemExit(0 if ok else 1)
