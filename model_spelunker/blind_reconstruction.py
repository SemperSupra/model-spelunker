import uuid
from typing import Any, Callable, Dict, List, Optional
from model_spelunker.models import (
    ExecutionDeviation,
    ExecutionTrace,
    OperationalMode,
    PublicationMethodIR,
)
from model_spelunker.provenance import generate_digest


class BlindExecutionRunner:
    """Runs blind independent reconstruction using only paper-derived Method IR.

    Enforces that author implementation artifacts are not accessed/viewed during this phase.
    """

    def __init__(self, method_ir: PublicationMethodIR):
        if not method_ir.frozen:
            raise ValueError("PublicationMethodIR must be frozen before starting blind reconstruction.")
        self.method_ir = method_ir
        self.deviations: List[ExecutionDeviation] = []

    def record_decision_or_deviation(
        self,
        field_name: str,
        assumed_value: Any,
        justification: str,
    ) -> ExecutionDeviation:
        """Records an explicit assumption or decision required to resolve missing/ambiguous/inferable paper details."""
        # Find paper evidence status
        paper_status = None
        for exp in self.method_ir.experiments:
            val = getattr(exp, field_name, None)
            if val is not None and hasattr(val, "status"):
                paper_status = val.status
                break

        dev = ExecutionDeviation(
            decision_id=f"dec-{uuid.uuid4().hex[:8]}",
            field_name=field_name,
            paper_status=paper_status,
            assumed_value=assumed_value,
            justification=justification,
        )
        self.deviations.append(dev)
        return dev

    def execute_experiment(
        self,
        experiment_id: str,
        execution_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
        execution_params: Dict[str, Any],
        seeds: List[int],
        env_snapshot: Dict[str, str],
    ) -> ExecutionTrace:
        """Executes the blind reconstruction function and records action traces and output digests."""
        exp_found = any(e.experiment_id == experiment_id for e in self.method_ir.experiments)
        if not exp_found:
            raise ValueError(f"Experiment ID {experiment_id} not found in PublicationMethodIR.")

        action_log = []
        action_log.append({
            "action": "start_blind_execution",
            "experiment_id": experiment_id,
            "params": execution_params,
            "seeds": seeds,
        })

        # Run user-supplied execution logic
        results = execution_fn(execution_params)

        action_log.append({
            "action": "complete_blind_execution",
            "results_keys": list(results.keys()),
        })

        output_digests = {}
        for k, v in results.items():
            output_digests[k] = generate_digest(v)

        trace = ExecutionTrace(
            trace_id=f"trace-blind-{uuid.uuid4().hex[:8]}",
            experiment_id=experiment_id,
            mode=OperationalMode.INDEPENDENT_REIMPLEMENTATION,
            command_actions=action_log,
            seeds_used=seeds,
            deviations=self.deviations,
            outputs=results,
            output_digests=output_digests,
            environment_snapshot=env_snapshot,
        )
        return trace
