from typing import Any, Dict, List
from pydantic import BaseModel
from model_spelunker.models import (
    EvidenceStatus,
    ExperimentProtocol,
    PublicationMethodIR,
    TerminalState,
)


class FieldAuditDetail(BaseModel):
    field_name: str
    status: EvidenceStatus
    locators: List[str]
    value: Any
    notes: str


class ExperimentCompletenessReport(BaseModel):
    experiment_id: str
    total_fields: int
    explicit_count: int
    inferable_count: int
    ambiguous_count: int
    missing_count: int
    contradictory_count: int
    not_applicable_count: int
    execution_blocking_unknowns: List[FieldAuditDetail]
    audited_fields: List[FieldAuditDetail]


class CompletenessReport(BaseModel):
    publication_id: str
    terminal_state: TerminalState
    can_proceed_to_blind_reconstruction: bool
    experiment_reports: List[ExperimentCompletenessReport]
    summary_execution_blocking_unknowns: List[str]


# Fields that are typically critical to execute an experiment deterministically
CRITICAL_EXECUTION_FIELDS = {
    "dataset_population_material",
    "preprocessing_transformations",
    "partitioning",
    "method_model_algorithm",
    "parameters_hyperparameters",
    "randomization_seeds_runs",
    "stopping_rules",
    "software_packages_environment",
}


def audit_experiment_protocol(exp: ExperimentProtocol) -> ExperimentCompletenessReport:
    """Audits an individual experiment protocol for field evidence completeness."""
    field_details: List[FieldAuditDetail] = []
    blocking_unknowns: List[FieldAuditDetail] = []

    explicit_cnt = 0
    inferable_cnt = 0
    ambiguous_cnt = 0
    missing_cnt = 0
    contradictory_cnt = 0
    na_cnt = 0

    for field_name, value in exp.model_dump().items():
        if field_name == "experiment_id":
            continue

        status = value.get("status")
        locators = value.get("locators", [])
        field_val = value.get("value")
        inference_notes = value.get("inference_notes") or ""
        uncertainty_notes = value.get("uncertainty_notes") or ""
        na_reason = value.get("not_applicable_reason") or ""

        notes = ""
        if status in (EvidenceStatus.EXPLICIT_PAPER, EvidenceStatus.EXPLICIT_SUPPLEMENT, EvidenceStatus.EXPLICIT_REFERENCED_ARTIFACT):
            explicit_cnt += 1
            notes = f"Explicitly stated in {locators}"
        elif status == EvidenceStatus.INFERABLE_WITH_EVIDENCE:
            inferable_cnt += 1
            notes = f"Inferred: {inference_notes}. Uncertainty: {uncertainty_notes}"
        elif status == EvidenceStatus.AMBIGUOUS:
            ambiguous_cnt += 1
            notes = f"Ambiguous detail. Notes: {uncertainty_notes}"
        elif status == EvidenceStatus.MISSING:
            missing_cnt += 1
            notes = "Field specification is missing from publication and explicitly linked material."
        elif status == EvidenceStatus.CONTRADICTORY:
            contradictory_cnt += 1
            notes = f"Contradictory information found across locators: {locators}"
        elif status == EvidenceStatus.NOT_APPLICABLE:
            na_cnt += 1
            notes = f"Not applicable: {na_reason}"

        detail = FieldAuditDetail(
            field_name=field_name,
            status=EvidenceStatus(status),
            locators=locators,
            value=field_val,
            notes=notes,
        )
        field_details.append(detail)

        # Check if field is blocking
        if status in (EvidenceStatus.MISSING, EvidenceStatus.AMBIGUOUS, EvidenceStatus.CONTRADICTORY):
            if field_name in CRITICAL_EXECUTION_FIELDS:
                blocking_unknowns.append(detail)
        elif status == EvidenceStatus.INFERABLE_WITH_EVIDENCE:
            # If high uncertainty or critical execution field without value
            if field_name in CRITICAL_EXECUTION_FIELDS and field_val is None:
                blocking_unknowns.append(detail)

    return ExperimentCompletenessReport(
        experiment_id=exp.experiment_id,
        total_fields=len(field_details),
        explicit_count=explicit_cnt,
        inferable_count=inferable_cnt,
        ambiguous_count=ambiguous_cnt,
        missing_count=missing_cnt,
        contradictory_count=contradictory_cnt,
        not_applicable_count=na_cnt,
        execution_blocking_unknowns=blocking_unknowns,
        audited_fields=field_details,
    )


def audit_publication_completeness(method_ir: PublicationMethodIR) -> CompletenessReport:
    """Audits a PublicationMethodIR and emits a CompletenessReport without scalar scores."""
    exp_reports = [audit_experiment_protocol(exp) for exp in method_ir.experiments]

    all_blocking_descriptions = []
    for exp_rep in exp_reports:
        for block in exp_rep.execution_blocking_unknowns:
            desc = f"Exp '{exp_rep.experiment_id}' field '{block.field_name}' [{block.status.value}]: {block.notes}"
            all_blocking_descriptions.append(desc)

    can_proceed = len(all_blocking_descriptions) == 0

    if not method_ir.frozen:
        terminal_state = TerminalState.MORE_EVIDENCE_REQUIRED
    elif can_proceed:
        terminal_state = TerminalState.METHOD_IR_FROZEN
    else:
        terminal_state = TerminalState.METHOD_INCOMPLETE

    return CompletenessReport(
        publication_id=method_ir.publication_id,
        terminal_state=terminal_state,
        can_proceed_to_blind_reconstruction=can_proceed,
        experiment_reports=exp_reports,
        summary_execution_blocking_unknowns=all_blocking_descriptions,
    )
