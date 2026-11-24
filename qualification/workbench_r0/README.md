# Read-only qualification workbench — integrated experimental slice

Experimental vertical slice only. No live operation, actor qualification or promotion. Reuses canonical run_task.py; no new scheduler, registry, HTTP service or CoS/Agent Dispatch dependency. CLI JSON is the same snapshot embedded in the human HTML view. Agents can consume discover and evidence JSON via CLI. R7 compares actual native read-only agent consumption of full vs compact CLI-derived evidence; autonomous discovery and invocation are not yet proven.

From any directory, invoke Python with the absolute path to workbench.py:

- discover
- status --receipts PATH
- evidence --receipts PATH --run-id ID
- render --receipts PATH --output NEW_HTML_FILE

Optional arguments on status/evidence/render: --resources PATH (strict R0 resource sidecars), --native-bundles PATH (trusted native task bundle directories), --intent PATH --spec PATH (synthetic plan review only). Discover lists these supported interfaces. Missing telemetry is UNKNOWN; incomplete coverage suppresses campaign CPU totals. Preview never grants execution or promotion authority.

Proofs: workbench-r0.yml uses canonical runner, browser, resource, plan and measured adaptive repetitions; overhead_proof.py accounts separately for Optuna dependency installation, freeze and campaign CPU. native-phase-task-r0.yml exercises native task evidence and a read-only Qwen Code interview using an exact reference checkout. These are framework-only experiments, not operational admission.

Input directory must contain only bounded synthetic canonical receipts. R0 deliberately labels every projection FRAMEWORK_PROVING_ONLY; do not use as an operational acceptance interface. Rendering never overwrites existing output. CLI invalid inputs return 2 with JSON error on stderr. UI has filters, receipt identity, theme selection and no external requests. The proof invokes the actual existing runner six times (three positive and three negative controls), then tests CLI parity and real Chromium journeys at three viewport sizes. Human usability and actual agent usability remain separate qualification tasks.

R8: reference VALUE control in each agent block, tool-event shape/error category diagnostics, counterbalanced full/compact comparison; no weakening of strict lineage. Hydration comparison uses separate clean venvs vs one reused venv, same pinned optimizer, same canonical tasks and exact dependency inventory comparison. Only synthetic results; reference failure invalidates representation attribution, not the observed failure itself.
