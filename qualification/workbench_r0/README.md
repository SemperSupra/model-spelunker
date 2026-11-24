# Read-only qualification workbench R0

Experimental vertical slice only. No live operation, actor qualification or promotion. Reuses canonical run_task.py; no new scheduler, registry, HTTP service or CoS/Agent Dispatch dependency. CLI JSON is the same snapshot embedded in the human HTML view. Agents consume discover and evidence JSON via CLI; no reasoning-agent usability claim yet.

From any directory, invoke Python with the absolute path to workbench.py:

- discover
- status --receipts PATH
- evidence --receipts PATH --run-id ID
- render --receipts PATH --output NEW_HTML_FILE

Input directory must contain only bounded synthetic canonical receipts. R0 deliberately labels every projection FRAMEWORK_PROVING_ONLY; do not use as an operational acceptance interface. Rendering never overwrites existing output. CLI invalid inputs return 2 with JSON error on stderr. UI has filters, receipt identity, theme selection and no external requests. The proof invokes the actual existing runner six times (three positive and three negative controls), then tests CLI parity and real Chromium journeys at three viewport sizes. Human usability and actual agent usability remain separate qualification tasks.
