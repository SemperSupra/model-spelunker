from typing import Any, Dict, List, Optional
from model_spelunker.models import (
    Claim,
    DiffClassification,
    EvidenceStatus,
    ExperimentProtocol,
    MethodDiffItem,
    MethodDiffReport,
    ProtocolFieldEvidence,
    PublicationMethodIR,
    ReconciliationReport,
)


class AuthorArtifactDiffEngine:
    """Diffs publication-derived Method IR against author-implemented Method IR and reconciles 3 evidence paths."""

    @staticmethod
    def classify_field_diff(
        field_name: str,
        pub_ev: ProtocolFieldEvidence,
        author_ev: ProtocolFieldEvidence,
    ) -> DiffClassification:
        """Classifies difference between publication evidence and author artifact evidence."""
        # Check equality of value
        if pub_ev.value == author_ev.value and pub_ev.status == author_ev.status:
            return DiffClassification.IMMATERIAL_DIFFERENCE

        if pub_ev.status == EvidenceStatus.MISSING:
            return DiffClassification.PUBLICATION_OMITTED_IMPLEMENTATION_DETAIL

        if pub_ev.status == EvidenceStatus.AMBIGUOUS:
            return DiffClassification.PUBLICATION_AMBIGUOUS_IMPLEMENTATION_CHOSE_BRANCH

        if pub_ev.status in (EvidenceStatus.EXPLICIT_PAPER, EvidenceStatus.EXPLICIT_SUPPLEMENT, EvidenceStatus.EXPLICIT_REFERENCED_ARTIFACT):
            if pub_ev.value != author_ev.value:
                return DiffClassification.PUBLICATION_ARTIFACT_CONTRADICTION

        if field_name in ("software_packages_environment", "hardware_instrumentation"):
            return DiffClassification.ENVIRONMENT_VERSION_DRIFT

        if pub_ev.value != author_ev.value:
            # Result equivalent or method incompatible
            return DiffClassification.RESULT_EQUIVALENT_METHOD_INCOMPATIBLE

        return DiffClassification.UNKNOWN

    def diff_experiment_protocols(
        self,
        pub_exp: ExperimentProtocol,
        author_exp: ExperimentProtocol,
    ) -> MethodDiffReport:
        """Diffs publication-derived experiment protocol against author artifact experiment protocol."""
        diff_items: List[MethodDiffItem] = []

        for field_name in pub_exp.__class__.model_fields.keys():
            if field_name == "experiment_id":
                continue

            pub_ev: ProtocolFieldEvidence = getattr(pub_exp, field_name)
            author_ev: ProtocolFieldEvidence = getattr(author_exp, field_name)

            if pub_ev.value != author_ev.value or pub_ev.status != author_ev.status:
                classification = self.classify_field_diff(field_name, pub_ev, author_ev)
                item = MethodDiffItem(
                    field_name=field_name,
                    publication_evidence=pub_ev,
                    author_evidence=author_ev,
                    classification=classification,
                    explanation=f"Publication specified '{pub_ev.value}' ({pub_ev.status.value}), author artifact specified '{author_ev.value}' ({author_ev.status.value}).",
                )
                diff_items.append(item)

        overall = "COMPATIBLE" if not diff_items else "METHOD_DIFFERENCES_DETECTED"
        return MethodDiffReport(
            experiment_id=pub_exp.experiment_id,
            diffs=diff_items,
            overall_method_compatibility=overall,
        )

    def reconcile_claim_evidence(
        self,
        claim: Claim,
        blind_result: Optional[Any],
        author_replay_result: Optional[Any],
        diff_reports: List[MethodDiffReport],
        tolerance_fn: Optional[Any] = None,
    ) -> ReconciliationReport:
        """Reconciles paper claimed result, blind reconstruction result, and author replay result."""
        claimed = claim.claimed_result

        # Check result compatibility between blind result and claimed result
        result_compatible = False
        if blind_result is not None and claimed is not None:
            if tolerance_fn:
                result_compatible = tolerance_fn(claimed, blind_result)
            elif isinstance(claimed, (int, float)) and isinstance(blind_result, (int, float)):
                # Default numeric tolerance of 1% or exact match
                result_compatible = abs(claimed - blind_result) <= 0.01 * abs(claimed) or claimed == blind_result
            else:
                result_compatible = str(claimed) == str(blind_result)

        # Method compatibility check
        has_contradictions = any(
            item.classification == DiffClassification.PUBLICATION_ARTIFACT_CONTRADICTION
            for report in diff_reports
            for item in report.diffs
        )
        has_omissions = any(
            item.classification == DiffClassification.PUBLICATION_OMITTED_IMPLEMENTATION_DETAIL
            for report in diff_reports
            for item in report.diffs
        )

        if has_contradictions:
            method_compat = "CONTRADICTORY_METHOD"
        elif has_omissions:
            method_compat = "METHOD_INCOMPLETE_OMISSIONS_FOUND"
        else:
            method_compat = "COMPATIBLE_METHOD"

        supported = result_compatible and (not has_contradictions)

        summary = (
            f"Claim '{claim.claim_id}': claimed={claimed}, blind_reconstruction={blind_result}, author_replay={author_replay_result}. "
            f"Result compatible: {result_compatible}. Method status: {method_compat}."
        )

        return ReconciliationReport(
            claim_id=claim.claim_id,
            claimed_result=claimed,
            blind_reconstruction_result=blind_result,
            author_replay_result=author_replay_result,
            result_compatibility="MATCH" if result_compatible else "DISCREPANCY",
            method_compatibility=method_compat,
            claim_supported=supported,
            summary_explanation=summary,
        )
