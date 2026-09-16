import pytest
from model_spelunker.models import (
    Claim,
    DiffClassification,
    EvidenceStatus,
    ExperimentProtocol,
    OperationalMode,
    ProtocolFieldEvidence,
    PublicationMethodIR,
    TerminalState,
)
from model_spelunker.completeness import audit_publication_completeness
from model_spelunker.blind_reconstruction import BlindExecutionRunner
from model_spelunker.artifact_diff import AuthorArtifactDiffEngine
from model_spelunker.provenance import map_to_ro_crate_provenance
from fixtures.specimens import get_siglip2_public_specimen, get_poisoned_redteam_fixtures


def test_siglip2_specimen_loading_and_audit():
    siglip = get_siglip2_public_specimen()
    assert siglip.publication_id == "arxiv:siglip2-2024"
    assert siglip.frozen is True
    assert len(siglip.claims) == 1
    assert len(siglip.experiments) == 1

    report = audit_publication_completeness(siglip)
    # SigLIP2 has missing seed/runs field
    assert report.terminal_state == TerminalState.METHOD_INCOMPLETE
    assert report.can_proceed_to_blind_reconstruction is False
    assert len(report.summary_execution_blocking_unknowns) == 1
    assert "randomization_seeds_runs" in report.summary_execution_blocking_unknowns[0]


def test_blind_reconstruction_runner():
    siglip = get_siglip2_public_specimen()
    runner = BlindExecutionRunner(siglip)

    # Record decision to resolve missing seed
    dev = runner.record_decision_or_deviation(
        field_name="randomization_seeds_runs",
        assumed_value=42,
        justification="Selected standard seed 42 as paper omitted seed.",
    )
    assert dev.field_name == "randomization_seeds_runs"
    assert dev.assumed_value == 42
    assert dev.paper_status == EvidenceStatus.MISSING

    # Run execution mock
    def mock_eval(params):
        return {"zero_shot_top1_accuracy": 0.801}

    trace = runner.execute_experiment(
        experiment_id="siglip2-exp-zeroshot-imagenet",
        execution_fn=mock_eval,
        execution_params={"model": "ViT-B/16"},
        seeds=[42],
        env_snapshot={"python": "3.12"},
    )

    assert trace.experiment_id == "siglip2-exp-zeroshot-imagenet"
    assert trace.mode == OperationalMode.INDEPENDENT_REIMPLEMENTATION
    assert trace.outputs["zero_shot_top1_accuracy"] == 0.801
    assert len(trace.deviations) == 1


def test_author_artifact_diff_and_reconciliation():
    siglip = get_siglip2_public_specimen()
    diff_engine = AuthorArtifactDiffEngine()

    # Create author artifact experiment with contradiction
    author_exp = siglip.experiments[0].model_copy(deep=True)
    author_exp.parameters_hyperparameters = ProtocolFieldEvidence(
        status=EvidenceStatus.EXPLICIT_REFERENCED_ARTIFACT,
        value="Learning rate 1e-4, AdamW",
        locators=["configs/train.py"],
    )

    diff_report = diff_engine.diff_experiment_protocols(siglip.experiments[0], author_exp)
    assert len(diff_report.diffs) >= 1

    found_contradiction = False
    for item in diff_report.diffs:
        if item.field_name == "parameters_hyperparameters":
            assert item.classification == DiffClassification.PUBLICATION_ARTIFACT_CONTRADICTION
            found_contradiction = True
    assert found_contradiction

    # Reconcile claim evidence
    rec_report = diff_engine.reconcile_claim_evidence(
        claim=siglip.claims[0],
        blind_result=0.802,
        author_replay_result=0.801,
        diff_reports=[diff_report],
    )
    assert rec_report.claim_id == "siglip2-claim-1"
    assert rec_report.result_compatibility == "MATCH"
    assert rec_report.method_compatibility == "CONTRADICTORY_METHOD"
    # Result matched but method had contradiction, so claim supported is False
    assert rec_report.claim_supported is False


def test_ro_crate_provenance_export():
    siglip = get_siglip2_public_specimen()
    crate = map_to_ro_crate_provenance(siglip)
    assert "@context" in crate
    assert "@graph" in crate
    assert len(crate["@graph"]) >= 4

    types = [item.get("@type") for item in crate["@graph"]]
    assert "CreativeWork" in types
    assert "Dataset" in types
    assert "ScholarlyArticle" in types
    assert "ScientificClaim" in types
    assert "LabProtocol" in types


def test_redteam_poisoned_fixtures():
    fixtures = get_poisoned_redteam_fixtures()
    diff_engine = AuthorArtifactDiffEngine()

    # Leakage fixture audit
    leak_rep = audit_publication_completeness(fixtures["leakage"])
    assert leak_rep.can_proceed_to_blind_reconstruction is False

    # Contradiction diff classification
    base_exp = get_siglip2_public_specimen().experiments[0]
    poison_exp = fixtures["contradiction"].experiments[0]
    diff_report = diff_engine.diff_experiment_protocols(base_exp, poison_exp)
    assert any(d.classification == DiffClassification.PUBLICATION_ARTIFACT_CONTRADICTION for d in diff_report.diffs)
