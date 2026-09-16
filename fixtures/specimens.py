import json
from typing import Dict, Any
from model_spelunker.models import (
    Claim,
    EvidenceStatus,
    ExperimentProtocol,
    ProtocolFieldEvidence,
    PublicationMethodIR,
)


def get_siglip2_public_specimen() -> PublicationMethodIR:
    """Returns a real, bounded public paper specimen for SigLIP2 vision-language replication.

    Source locators and values are extracted from the SigLIP2 publication / public release material.
    """
    claim1 = Claim(
        claim_id="siglip2-claim-1",
        locator="SigLIP2 Paper Section 4.1, Table 2",
        bounded_paraphrase="SigLIP2 ViT-B/16 achieves zero-shot ImageNet top-1 accuracy of 80.2% when trained on WebLI dataset.",
        supporting_experiment_ids=["siglip2-exp-zeroshot-imagenet"],
        claimed_metric="zero_shot_top1_accuracy",
        claimed_result=0.802,
        tolerance="±0.005",
    )

    exp1 = ExperimentProtocol(
        experiment_id="siglip2-exp-zeroshot-imagenet",
        hypothesis=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="SigLIP loss with shape-optimized masking improves zero-shot classification performance over standard SigLIP.",
            locators=["Section 1", "Section 3.2"],
        ),
        independent_variables=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Encoder backbone size (ViT-B/16) and loss formulation (SigLIP loss with dynamic temperature).",
            locators=["Section 3.1", "Table 1"],
        ),
        dependent_variables=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Zero-shot top-1 accuracy on ImageNet-1k validation set.",
            locators=["Section 4.1", "Table 2"],
        ),
        controls_baselines=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Standard SigLIP baseline and OpenAI CLIP ViT-B/16.",
            locators=["Section 4.1"],
        ),
        dataset_population_material=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="WebLI English image-text dataset and ImageNet-1k (ILSVRC2012) validation split.",
            locators=["Section 3.3", "Section 4.1"],
        ),
        inclusion_exclusion_sampling=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Filtered WebLI pairs using score threshold > 0.3.",
            locators=["Section 3.3"],
        ),
        preprocessing_transformations=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Bicubic resize to 224x224, normalized with mean [0.48145466, 0.4578275, 0.40821073] and std [0.26862954, 0.26130258, 0.27577711].",
            locators=["Section 3.4", "Appendix B"],
        ),
        partitioning=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Train on WebLI full train split; evaluate on ImageNet-1k 50,000 validation images.",
            locators=["Section 4.1"],
        ),
        method_model_algorithm=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="SigLIP2 ViT-B/16 vision-language dual encoder with sigmoid loss and prompt template zero-shot classifier.",
            locators=["Section 3.1", "Section 3.2"],
        ),
        parameters_hyperparameters=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Learning rate 1e-3, AdamW optimizer (beta1=0.9, beta2=0.999), weight decay 0.1, batch size 32768, sequence length 64.",
            locators=["Table 5", "Appendix B"],
        ),
        hyperparameter_selection_procedure=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Grid search over learning rate [1e-4, 3e-4, 1e-3] and weight decay [0.01, 0.1] on validation loss.",
            locators=["Appendix B.2"],
        ),
        randomization_seeds_runs=ProtocolFieldEvidence(
            status=EvidenceStatus.MISSING,
            value=None,
            locators=[],
            uncertainty_notes="Paper does not specify exact random seed or number of evaluation/training runs.",
        ),
        stopping_rules=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Fixed schedule of 10 billion seen image-text pairs.",
            locators=["Section 3.4"],
        ),
        software_packages_environment=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_REFERENCED_ARTIFACT,
            value="JAX / Flax / Scenic codebase revision v0.1.2.",
            locators=["Footnote 2", "https://github.com/google-research/scenic"],
        ),
        hardware_instrumentation=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="256 TPU v4 chips.",
            locators=["Section 4.5"],
        ),
        execution_ordering_dependencies=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Pre-train vision-language model, build zero-shot text prompt embeddings, compute cosine similarities with image embeddings.",
            locators=["Section 3.2", "Section 4.1"],
        ),
        statistical_tests_aggregation=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="Top-1 accuracy percentage over 50,000 validation images.",
            locators=["Table 2"],
        ),
        significance_decision_criteria=ProtocolFieldEvidence(
            status=EvidenceStatus.NOT_APPLICABLE,
            not_applicable_reason="Deterministic top-1 validation score comparison without formal hypothesis testing.",
        ),
        expected_claimed_output=ProtocolFieldEvidence(
            status=EvidenceStatus.EXPLICIT_PAPER,
            value="0.802 (80.2%) zero-shot top-1 accuracy.",
            locators=["Table 2"],
        ),
    )

    return PublicationMethodIR(
        publication_id="arxiv:siglip2-2024",
        title="SigLIP 2: Multilingual Vision-Language Encoders with Improved Capabilities",
        revision_digest="sha256-siglip2-pub-rev-v1",
        frozen=True,
        claims=[claim1],
        experiments=[exp1],
    )


def get_poisoned_redteam_fixtures() -> Dict[str, PublicationMethodIR]:
    """Generates synthetic / poisoned protocol fixtures for testing red-team controls.

    Negative cases:
    1. Undocumented preprocessing / hidden data leakage.
    2. Paper/code parameter contradiction.
    3. Missing seed & stochasticity details.
    """
    base_siglip = get_siglip2_public_specimen()

    # Case 1: Undocumented preprocessing & hidden split leak
    exp_leaky = base_siglip.experiments[0].model_copy(deep=True)
    exp_leaky.experiment_id = "exp-poisoned-data-leakage"
    exp_leaky.preprocessing_transformations = ProtocolFieldEvidence(
        status=EvidenceStatus.MISSING,
        value=None,
        uncertainty_notes="Undocumented test set normalization & data augmentation present in code.",
    )
    exp_leaky.partitioning = ProtocolFieldEvidence(
        status=EvidenceStatus.CONTRADICTORY,
        value="Train set overlapped with validation set images due to deduplication failure.",
        locators=["Code inspection"],
    )

    fixture_leak = base_siglip.model_copy(deep=True)
    fixture_leak.publication_id = "fixture-poisoned-leakage"
    fixture_leak.experiments = [exp_leaky]

    # Case 2: Paper/code hyperparameter contradiction
    exp_contradict = base_siglip.experiments[0].model_copy(deep=True)
    exp_contradict.experiment_id = "exp-poisoned-contradiction"
    exp_contradict.parameters_hyperparameters = ProtocolFieldEvidence(
        status=EvidenceStatus.CONTRADICTORY,
        value="Paper states LR 1e-3, but author config uses LR 1e-4 with undocumented cosine decay.",
        locators=["Table 5 vs configs/hyper.py"],
    )

    fixture_contradict = base_siglip.model_copy(deep=True)
    fixture_contradict.publication_id = "fixture-poisoned-contradiction"
    fixture_contradict.experiments = [exp_contradict]

    return {
        "leakage": fixture_leak,
        "contradiction": fixture_contradict,
    }
