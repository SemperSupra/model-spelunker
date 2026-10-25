import json
import hashlib
import os
import pytest

REP0_DIR = "paperbench_rice_rep0"

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


@pytest.fixture
def inputs_data(manifest):
    data = {}
    for name, spec in manifest["inputs"].items():
        local_path = spec["local_path"]
        assert os.path.exists(local_path), f"Input file {local_path} missing"
        with open(local_path, "r", encoding="utf-8") as f:
            data[name] = f.read()
    return data


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
            raw = f.read()
        assert len(raw) == spec["size_bytes"], f"Size mismatch for {name}"
        assert hashlib.sha256(raw).hexdigest() == spec["sha256"], f"SHA mismatch for {name}"

    assert manifest["inputs"]["paper.md"]["sha256"] == "e69c502c0c16f860160da8368e5b4fc5ee3da36275fe0571350bdd03b3477e03"
    assert manifest["inputs"]["paper.md"]["size_bytes"] == 106169
    assert manifest["inputs"]["addendum.md"]["sha256"] == "d62c727e9aaac69165d0bbeb2b1c4df7f1c8a183c5906d9b0e44cf9401153b43"
    assert manifest["inputs"]["addendum.md"]["size_bytes"] == 5102


def test_no_held_out_content_or_paths():
    for root, _, files in os.walk(REP0_DIR):
        for fname in files:
            if fname == "paper.md":
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for pattern in HELD_OUT_PATTERNS:
                assert pattern not in content, f"Held-out pattern '{pattern}' found in {fpath}"
                assert pattern not in fpath, f"Held-out pattern '{pattern}' found in filename {fpath}"

            if fname != "source_manifest.json":
                assert "chengzelei/RICE" not in content, f"Author repo found in extraction artifact {fpath}"


def test_method_ir_evidence_locators_and_source_binding(method_ir, inputs_data):
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

        if status == "MISSING":
            assert len(field_data.get("evidence_spans", [])) == 0, f"MISSING field {field_name} must not contain evidence spans"
            assert "absence_assessment" in field_data, f"MISSING field {field_name} must contain absence_assessment"
            absence = field_data["absence_assessment"]
            assert "search_scope" in absence and len(absence["search_scope"]) > 0
            assert "notes" in absence and len(absence["notes"]) > 0
        else:
            spans = field_data.get("evidence_spans", [])
            if not spans and "evidence" in field_data:
                spans = [field_data["evidence"]]

            assert len(spans) > 0, f"Field {field_name} with status {status} must contain at least one evidence span"

            if status in ("AMBIGUOUS", "CONTRADICTORY"):
                assert len(spans) >= 2, f"Field {field_name} with status {status} must contain at least two evidence spans for multi-source reasoning"
                artifacts = {span["artifact"] for span in spans}
                assert len(artifacts) >= 2, f"Field {field_name} with status {status} must cite multiple distinct artifacts"

            for span in spans:
                art_name = span["artifact"]
                assert art_name in inputs_data, f"Span in field {field_name} names invalid artifact {art_name}"
                locator = span.get("locator", "")
                excerpt = span.get("excerpt", "")
                excerpt_sha256 = span.get("excerpt_sha256", "")

                assert len(locator) > 0, f"Locator empty in field {field_name}"
                assert len(excerpt) > 0, f"Excerpt empty in field {field_name}"

                calc_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                assert excerpt_sha256 == calc_hash, f"Excerpt SHA mismatch for field {field_name}"

                # Mechanical source-occurrence validation:
                # Prove every quoted evidence excerpt actually occurs in the declared artifact
                artifact_content = inputs_data[art_name]
                assert excerpt in artifact_content, f"Evidence excerpt for field {field_name} NOT FOUND in declared artifact {art_name}"

            # If semantic field value contains claims sourced from addendum, verify it has an evidence span from addendum.md
            val_text = field_data.get("value", "")
            if "addendum" in val_text.lower():
                cited_arts = {span["artifact"] for span in spans}
                assert "addendum.md" in cited_arts, f"Field {field_name} value mentions addendum but lacks evidence span from addendum.md"


def test_deliberate_source_swap_fails_binding(method_ir, inputs_data):
    # Select a known span that is in paper.md only
    sample_span = None
    for field_name, field_data in method_ir["method_fields"].items():
        for span in field_data.get("evidence_spans", []):
            if span["artifact"] == "paper.md":
                sample_span = span
                break
        if sample_span:
            break

    assert sample_span is not None, "Could not find a paper.md span for negative control test"

    excerpt = sample_span["excerpt"]
    # Check that excerpt is present in paper.md
    assert excerpt in inputs_data["paper.md"]
    # Verify that swapping artifact to addendum.md causes source-occurrence check to fail
    wrong_artifact = "addendum.md"
    assert excerpt not in inputs_data[wrong_artifact], "Negative control failed: excerpt unexpectedly found in swapped artifact"


def test_completeness_report_and_terminal_state(completeness_report, method_ir):
    assert completeness_report["terminal_state"] == "METHOD_INCOMPLETE"
    assert completeness_report["independent_reimplementation_runnable_from_publication_inputs_alone"] is False
    assert len(completeness_report["model_spelunker_revision"]) == 40
    assert len(completeness_report["minimum_execution_blocking_unknowns"]) > 0

    # Cross-artifact mechanical reconciliation check
    method_fields = method_ir["method_fields"]
    status_counts = {}
    ambiguous_fields_in_ir = []
    missing_fields_in_ir = []

    for f_name, f_data in method_fields.items():
        st = f_data["status"]
        status_counts[st] = status_counts.get(st, 0) + 1
        if st in ("AMBIGUOUS", "CONTRADICTORY"):
            ambiguous_fields_in_ir.append(f_name)
        elif st == "MISSING":
            missing_fields_in_ir.append(f_name)

    # Check status counts
    rep_summary = completeness_report.get("field_status_summary", {})
    assert rep_summary == status_counts, f"Completeness report status summary {rep_summary} does not match IR counts {status_counts}"

    # Check field presence in lists
    rep_amb_fields = [item["field"] for item in completeness_report.get("ambiguity_list", [])]
    assert sorted(rep_amb_fields) == sorted(ambiguous_fields_in_ir), "Ambiguity list in completeness report does not match IR ambiguous fields"

    rep_miss_fields = [item["field"] for item in completeness_report.get("missing_details_list", [])]
    assert sorted(rep_miss_fields) == sorted(missing_fields_in_ir), "Missing details list in completeness report does not match IR missing fields"

    # Check for stale or contradictory descriptions in ambiguity list
    for item in completeness_report.get("ambiguity_list", []):
        f_name = item["field"]
        issue = item["issue"]
        assert f_name in method_fields, f"Completeness report names field {f_name} not present in Method IR"
        ir_val = method_fields[f_name].get("value", "")
        if "Section 3.2" in issue:
            assert "Section 3.2" in ir_val, f"Completeness report contains stale ambiguity description referring to Section 3.2 for field {f_name}"


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
