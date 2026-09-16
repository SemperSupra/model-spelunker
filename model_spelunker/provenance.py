import hashlib
import json
from typing import Any, Dict, List, Optional
from model_spelunker.models import PublicationMethodIR, ExecutionTrace


def generate_digest(data: Any) -> str:
    """Generates a deterministic SHA256 hex digest for JSON-serializable data."""
    dumped = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def map_to_ro_crate_provenance(
    method_ir: PublicationMethodIR,
    trace: Optional[ExecutionTrace] = None,
    extra_artifacts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Maps PublicationMethodIR and optional ExecutionTrace into an RO-Crate / W3C-PROV compatible metadata dictionary."""
    crate_id = f"ro-crate-{method_ir.publication_id}"

    graph: List[Dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
            "about": {"@id": "./"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": f"Research Object for {method_ir.title}",
            "identifier": method_ir.publication_id,
            "hasPart": [],
        },
        {
            "@id": f"pub:{method_ir.publication_id}",
            "@type": "ScholarlyArticle",
            "name": method_ir.title,
            "revisionDigest": method_ir.revision_digest,
        },
    ]

    # Map Claims
    claim_nodes = []
    for claim in method_ir.claims:
        claim_node = {
            "@id": f"claim:{claim.claim_id}",
            "@type": "ScientificClaim",
            "locator": claim.locator,
            "description": claim.bounded_paraphrase,
            "supportingExperiments": [f"exp:{eid}" for eid in claim.supporting_experiment_ids],
            "claimedMetric": claim.claimed_metric,
            "claimedResult": claim.claimed_result,
        }
        claim_nodes.append(claim_node)
        graph.append(claim_node)

    # Map Experiments
    for exp in method_ir.experiments:
        exp_node = {
            "@id": f"exp:{exp.experiment_id}",
            "@type": "LabProtocol",
            "name": exp.experiment_id,
            "hypothesis": exp.hypothesis.model_dump(),
            "methodology": {
                "independent_variables": exp.independent_variables.model_dump(),
                "dependent_variables": exp.dependent_variables.model_dump(),
                "controls_baselines": exp.controls_baselines.model_dump(),
                "dataset": exp.dataset_population_material.model_dump(),
                "preprocessing": exp.preprocessing_transformations.model_dump(),
                "partitioning": exp.partitioning.model_dump(),
                "algorithm": exp.method_model_algorithm.model_dump(),
                "hyperparameters": exp.parameters_hyperparameters.model_dump(),
                "randomization": exp.randomization_seeds_runs.model_dump(),
                "stopping_rules": exp.stopping_rules.model_dump(),
                "environment": exp.software_packages_environment.model_dump(),
                "hardware": exp.hardware_instrumentation.model_dump(),
            },
        }
        graph.append(exp_node)

    # Map Execution Trace if present
    if trace:
        trace_node = {
            "@id": f"trace:{trace.trace_id}",
            "@type": "CreateAction",
            "name": f"Execution Trace for {trace.experiment_id}",
            "instrument": {"@id": f"exp:{trace.experiment_id}"},
            "operationalMode": trace.mode.value,
            "commandActions": trace.command_actions,
            "environmentSnapshot": trace.environment_snapshot,
            "outputDigests": trace.output_digests,
            "seedsUsed": trace.seeds_used,
            "deviations": [dev.model_dump() for dev in trace.deviations],
        }
        graph.append(trace_node)

    if extra_artifacts:
        for art in extra_artifacts:
            art_id = art.get("uri") or f"artifact:{generate_digest(art)}"
            art_node = {
                "@id": art_id,
                "@type": "MediaObject",
                "name": art.get("name", "Artifact"),
                "digest": generate_digest(art),
                "details": art,
            }
            graph.append(art_node)

    ro_crate_doc = {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": graph,
        "crate_digest": generate_digest(graph),
    }
    return ro_crate_doc
