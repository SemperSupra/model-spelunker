from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class OperationalMode(str, Enum):
    SAME_METHOD_SAME_ENV_REPEAT = "SAME_METHOD_SAME_ENV_REPEAT"
    SAME_METHOD_CHANGED_ENV = "SAME_METHOD_CHANGED_ENV"
    INDEPENDENT_REIMPLEMENTATION = "INDEPENDENT_REIMPLEMENTATION"
    AUTHOR_ARTIFACT_REPLAY = "AUTHOR_ARTIFACT_REPLAY"
    NEW_DATA_OR_POPULATION_REPLICATION = "NEW_DATA_OR_POPULATION_REPLICATION"


class EvidenceStatus(str, Enum):
    EXPLICIT_PAPER = "EXPLICIT_PAPER"
    EXPLICIT_SUPPLEMENT = "EXPLICIT_SUPPLEMENT"
    EXPLICIT_REFERENCED_ARTIFACT = "EXPLICIT_REFERENCED_ARTIFACT"
    INFERABLE_WITH_EVIDENCE = "INFERABLE_WITH_EVIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTORY = "CONTRADICTORY"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TerminalState(str, Enum):
    METHOD_IR_FROZEN = "METHOD_IR_FROZEN"
    METHOD_INCOMPLETE = "METHOD_INCOMPLETE"
    SOURCE_ARTIFACT_BLOCKED = "SOURCE_ARTIFACT_BLOCKED"
    BLINDNESS_NOT_ENFORCEABLE = "BLINDNESS_NOT_ENFORCEABLE"
    PROTOCOL_IR_OVERBUILT = "PROTOCOL_IR_OVERBUILT"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"


class DiffClassification(str, Enum):
    PUBLICATION_OMITTED_IMPLEMENTATION_DETAIL = "publication omitted implementation detail"
    PUBLICATION_AMBIGUOUS_IMPLEMENTATION_CHOSE_BRANCH = "publication ambiguous but implementation chose one branch"
    PUBLICATION_ARTIFACT_CONTRADICTION = "publication/artifact contradiction"
    INDEPENDENT_IMPLEMENTATION_DEFECT = "independent implementation defect"
    ENVIRONMENT_VERSION_DRIFT = "environment/version drift"
    RESULT_EQUIVALENT_METHOD_INCOMPATIBLE = "result-equivalent but method-incompatible choice"
    IMMATERIAL_DIFFERENCE = "immaterial difference"
    UNKNOWN = "UNKNOWN"


class ProtocolFieldEvidence(BaseModel):
    value: Any = None
    status: EvidenceStatus
    locators: List[str] = Field(default_factory=list)
    inference_notes: Optional[str] = None
    uncertainty_notes: Optional[str] = None
    not_applicable_reason: Optional[str] = None


class Claim(BaseModel):
    claim_id: str
    locator: str
    bounded_paraphrase: str
    supporting_experiment_ids: List[str]
    claimed_metric: Optional[str] = None
    claimed_result: Optional[Union[float, str, dict]] = None
    tolerance: Optional[str] = None


class ExperimentProtocol(BaseModel):
    experiment_id: str
    hypothesis: ProtocolFieldEvidence
    independent_variables: ProtocolFieldEvidence
    dependent_variables: ProtocolFieldEvidence
    controls_baselines: ProtocolFieldEvidence
    dataset_population_material: ProtocolFieldEvidence
    inclusion_exclusion_sampling: ProtocolFieldEvidence
    preprocessing_transformations: ProtocolFieldEvidence
    partitioning: ProtocolFieldEvidence
    method_model_algorithm: ProtocolFieldEvidence
    parameters_hyperparameters: ProtocolFieldEvidence
    hyperparameter_selection_procedure: ProtocolFieldEvidence
    randomization_seeds_runs: ProtocolFieldEvidence
    stopping_rules: ProtocolFieldEvidence
    software_packages_environment: ProtocolFieldEvidence
    hardware_instrumentation: ProtocolFieldEvidence
    execution_ordering_dependencies: ProtocolFieldEvidence
    statistical_tests_aggregation: ProtocolFieldEvidence
    significance_decision_criteria: ProtocolFieldEvidence
    expected_claimed_output: ProtocolFieldEvidence


class PublicationMethodIR(BaseModel):
    publication_id: str
    title: str
    revision_digest: str
    frozen: bool = False
    claims: List[Claim]
    experiments: List[ExperimentProtocol]


class ExecutionDeviation(BaseModel):
    decision_id: str
    field_name: str
    paper_status: EvidenceStatus
    assumed_value: Any
    justification: str


class ExecutionTrace(BaseModel):
    trace_id: str
    experiment_id: str
    mode: OperationalMode
    command_actions: List[Dict[str, Any]]
    seeds_used: List[int]
    deviations: List[ExecutionDeviation]
    outputs: Dict[str, Any]
    output_digests: Dict[str, str]
    environment_snapshot: Dict[str, str]


class MethodDiffItem(BaseModel):
    field_name: str
    publication_evidence: ProtocolFieldEvidence
    author_evidence: ProtocolFieldEvidence
    classification: DiffClassification
    explanation: str


class MethodDiffReport(BaseModel):
    experiment_id: str
    diffs: List[MethodDiffItem]
    overall_method_compatibility: str


class ReconciliationReport(BaseModel):
    claim_id: str
    claimed_result: Any
    blind_reconstruction_result: Optional[Any]
    author_replay_result: Optional[Any]
    result_compatibility: str
    method_compatibility: str
    claim_supported: bool
    summary_explanation: str
