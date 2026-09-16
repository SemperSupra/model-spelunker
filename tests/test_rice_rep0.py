import json
import hashlib
import os
import pytest

REP0_DIR = "paperbench_rice_rep0"

# Held-out oracle patterns that must not appear in treatment/extraction artifacts
HELD_OUT_PATTERNS = [
    "rubric.json",
    "judge.addendum.md",
    "paperbench/data/papers/rice/rubric.json",
    "paperbench/data/papers/rice/judge.addendum.md"
]

@pytest.fixture
def manifest():
    manifest_path = os.path.join(REP0_DIR, "source_manifest.json")
    assert os.path.exists(manifest_path), "source_manifest.json must exist"
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def method_ir():
    ir_path = os.path.join(REP0_DIR, "method_ir.json")
    assert os.path.exists(ir_path), "method_ir.json must exist"
    with open(ir_path, "r", encoding="utf-8") as f:
        return json.load(f)

@pytest.fixture
def completeness_report():
    report_path = os.path.join(REP0_DIR, "completeness_report.json")
    assert os.path.exists(report_path), "completeness_report.json must exist"
    with open(report_path, "r", encoding="utf-8") as f:
        return json.load(f)

def test_source_manifest_allowed_paths_and_digests(manifest):
    assert manifest["upstream_repository"] == "openai/frontier-evals"
    assert manifest["upstream_revision"] == "51052cede8cc608f95bb00346635e03759013e5a"
    assert manifest["paper_id"] == "rice"

    allowed_inputs = {"paper.md", "addendum.md", "config.yaml"}
    assert set(manifest["inputs"].keys()) == allowed_inputs

    for name, spec in manifest["inputs"].items():
        local_path = spec["local_path"]
        assert os.path.exists(local_path), f"Input file {local_path} missing"
        with open(local_path, "rb") as f:
            data = f.read()
        assert len(data) == spec["size_bytes"], f"Size mismatch for {name}"
        assert hashlib.sha256(data).hexdigest() == spec["sha256"], f"SHA mismatch for {name}"

    # Verify specific pinned hydrated bytes
    assert manifest["inputs"]["paper.md"]["sha256"] == "e69c502c0c16f860160da8368e5b4fc5ee3da36275fe0571350bdd03b3477e03"
    assert manifest["inputs"]["paper.md"]["size_bytes"] == 106169
    assert manifest["inputs"]["addendum.md"]["sha256"] == "d62c727e9aaac69165d0bbeb2b1c4df7f1c8a183c5906d9b0e44cf9401153b43"
    assert manifest["inputs"]["addendum.md"]["size_bytes"] == 5102

def test_no_held_out_content_or_paths():
    for root, _, files in os.walk(REP0_DIR):
        for fname in files:
            # Skip checking inputs/paper.md for author repo link since the publication paper itself cites it
            if fname == "paper.md":
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for pattern in HELD_OUT_PATTERNS:
                assert pattern not in content, f"Held-out pattern '{pattern}' found in {fpath}"
                assert pattern not in fpath, f"Held-out pattern '{pattern}' found in filename {fpath}"

            # Ensure extraction artifacts do not reference external author repo or rubric
            if fname != "source_manifest.json":
                assert "chengzelei/RICE" not in content, f"Author repo found in extraction artifact {fpath}"

def test_method_ir_evidence_locators_and_hashes(method_ir):
    valid_statuses = {
        "EXPLICIT_PAPER",
        "EXPLICIT_ADDENDUM",
        "INFERABLE_WITH_EVIDENCE",
        "AMBIGUOUS",
        "CONTRADICTORY",
        "MISSING",
        "NOT_APPLICABLE"
    }

    for field_name, field_data in method_ir["method_fields"].items():
        status = field_data["status"]
        assert status in valid_statuses, f"Invalid status {status} in field {field_name}"

        if status not in ("MISSING", "NOT_APPLICABLE"):
            assert "evidence" in field_data, f"Field {field_name} missing evidence locator"
            evidence = field_data["evidence"]
            assert evidence["artifact"] in ("paper.md", "addendum.md", "config.yaml")
            assert len(evidence["locator"]) > 0
            assert len(evidence["excerpt"]) > 0

            # Verify excerpt SHA
            calc_hash = hashlib.sha256(evidence["excerpt"].encode("utf-8")).hexdigest()
            assert evidence["excerpt_sha256"] == calc_hash, f"Excerpt SHA mismatch for field {field_name}"
            assert not evidence["excerpt_sha256"].startswith("sha256-..."), "Placeholder hash found"

def test_completeness_report_and_terminal_state(completeness_report):
    assert completeness_report["terminal_state"] == "METHOD_INCOMPLETE"
    assert completeness_report["independent_reimplementation_runnable_from_publication_inputs_alone"] is False
    assert len(completeness_report["model_spelunker_revision"]) == 40
    assert len(completeness_report["minimum_execution_blocking_unknowns"]) > 0

def test_deterministic_digests():
    digests_path = os.path.join(REP0_DIR, "digests.json")
    assert os.path.exists(digests_path)
    with open(digests_path, "r", encoding="utf-8") as f:
        stored_digests = json.load(f)

    for fname, expected_hash in stored_digests.items():
        fpath = os.path.join(REP0_DIR, fname)
        assert os.path.exists(fpath)
        with open(fpath, "rb") as f:
            data = f.read()
        calc_hash = hashlib.sha256(data).hexdigest()
        assert calc_hash == expected_hash, f"Digest mismatch for {fname}"
