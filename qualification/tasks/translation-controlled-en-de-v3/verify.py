#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

THRESHOLD = 0.72

REFERENCES = [
    "Dienst R4 hat 8 von 12 Anfragen akzeptiert.",
    "Der Zustand bleibt UNKNOWN, nachdem die Prüfsumme ZX-19 fehlgeschlagen ist.",
    "RUN-5 nicht vor 17:45 UTC neu starten.",
    "Release 2026.09.25 hat 4 von 6 Tests bestanden.",
]

POSITIVE_PARAPHRASE = [
    "Dienst R4 akzeptierte 8 von 12 Anfragen.",
    "Der Zustand bleibt UNKNOWN, nachdem die Prüfsumme ZX-19 fehlschlug.",
    "RUN-5 nicht vor 17:45 UTC neu starten.",
    "Release 2026.09.25 bestand 4 von 6 Tests.",
]

NEGATIVE_CONTROL = [
    "Dienst R4 lehnte 8 von 12 Anfragen ab.",
    "Der Zustand ist READY, nachdem die Prüfsumme ZX-19 erfolgreich war.",
    "RUN-5 vor 17:45 UTC neu starten.",
    "Release 2026.09.25 hat 4 von 6 Tests nicht bestanden.",
]

PROTECTED = [
    "R4",
    "UNKNOWN",
    "ZX-19",
    "RUN-5",
    "17:45 UTC",
    "Release",
    "2026.09.25",
    "8",
    "12",
    "4",
    "6",
]


def norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def char_ngrams(value: str, order: int) -> Counter[str]:
    return Counter(value[i : i + order] for i in range(max(0, len(value) - order + 1)))


def corpus_chrf(reference: list[str], hypothesis: list[str], beta: float = 2.0) -> float:
    precision_total = 0.0
    recall_total = 0.0
    cells = 0
    for ref, hyp in zip(reference, hypothesis):
        ref = norm(ref)
        hyp = norm(hyp)
        for order in range(1, 7):
            ref_grams = char_ngrams(ref, order)
            hyp_grams = char_ngrams(hyp, order)
            overlap = sum((ref_grams & hyp_grams).values())
            hyp_count = sum(hyp_grams.values())
            ref_count = sum(ref_grams.values())
            precision_total += overlap / hyp_count if hyp_count else 0.0
            recall_total += overlap / ref_count if ref_count else 0.0
            cells += 1
    precision = precision_total / cells
    recall = recall_total / cells
    if precision == 0.0 and recall == 0.0:
        return 0.0
    beta2 = beta * beta
    return (1.0 + beta2) * precision * recall / (beta2 * precision + recall)


def semantic_slots(rows: list[str]) -> tuple[bool, str]:
    if not re.search(r"\b8\s+von\s+12\b", rows[0], flags=re.IGNORECASE):
        return False, "slot:t1-count-relation"
    if "UNKNOWN" not in rows[1] or "ZX-19" not in rows[1]:
        return False, "slot:t2-state-checksum"
    lower3 = rows[2].lower()
    if "run-5" not in lower3 or "17:45 utc" not in lower3:
        return False, "slot:t3-identifiers"
    if "nicht" not in lower3 or lower3.index("nicht") > lower3.index("17:45 utc"):
        return False, "slot:t3-negation-time"
    if not re.search(r"\b4\s+von\s+6\b", rows[3], flags=re.IGNORECASE):
        return False, "slot:t4-count-relation"
    return True, "pass"


def check_value(value: object) -> tuple[bool, str, float]:
    if not isinstance(value, dict):
        return False, "top-level-type", 0.0
    if set(value) != {"schema_version", "source_locale", "target_locale", "translations"}:
        return False, "top-level-schema", 0.0
    if value.get("schema_version") != 1:
        return False, "schema-version", 0.0
    if value.get("source_locale") != "en-US" or value.get("target_locale") != "de-DE":
        return False, "locale", 0.0
    translations = value.get("translations")
    if not isinstance(translations, list) or len(translations) != 4:
        return False, "translation-count", 0.0

    expected_ids = ["t1", "t2", "t3", "t4"]
    rows: list[str] = []
    for index, (row, expected_id) in enumerate(zip(translations, expected_ids)):
        if not isinstance(row, dict) or set(row) != {"id", "text"}:
            return False, f"row-schema:{index}", 0.0
        if row.get("id") != expected_id or not isinstance(row.get("text"), str):
            return False, f"row-id-or-text:{index}", 0.0
        rows.append(norm(row["text"]))

    joined = "\n".join(rows)
    for token in PROTECTED:
        if token not in joined:
            return False, f"protected-token:{token}", 0.0

    slots_ok, slot_reason = semantic_slots(rows)
    if not slots_ok:
        return False, slot_reason, 0.0

    score = corpus_chrf(REFERENCES, rows)
    if score < THRESHOLD:
        return False, f"character-fscore:{score:.6f}", score
    return True, "pass", score


def check(root: Path) -> tuple[bool, str, float]:
    path = root / "translation.json"
    if not path.is_file():
        return False, "missing-output", 0.0
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, "invalid-json", 0.0
    return check_value(value)


def payload(rows: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_locale": "en-US",
        "target_locale": "de-DE",
        "translations": [
            {"id": f"t{i+1}", "text": text} for i, text in enumerate(rows)
        ],
    }


def self_test() -> int:
    canonical = payload(REFERENCES)
    ok, reason, score = check_value(canonical)
    assert ok and score > 0.99, (reason, score)

    paraphrase = payload(POSITIVE_PARAPHRASE)
    ok, reason, score = check_value(paraphrase)
    assert ok and score >= THRESHOLD, (reason, score)

    negative = payload(NEGATIVE_CONTROL)
    ok, _, _ = check_value(negative)
    assert not ok

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "translation.json").write_text(
            json.dumps(paraphrase, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        ok, reason, score = check(root)
        assert ok, (reason, score)

    print(
        json.dumps(
            {
                "status": "PASS",
                "threshold": THRESHOLD,
                "positive_paraphrase_score": corpus_chrf(REFERENCES, POSITIVE_PARAPHRASE),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) != 2:
        raise SystemExit(2)
    ok, reason, score = check(Path(sys.argv[1]))
    print(json.dumps({"ok": ok, "reason": reason, "character_fscore": score}, sort_keys=True))
    raise SystemExit(0 if ok else 1)
