# Portable dispatcher semantic reconstruction v0

**Nature:** source-known real compiled binary with stripped helper symbols, public-safe. This measures *semantic behavior reconstruction* from actual machine code, not binary type labeling. It does **not** yet prove Ghidra/MCP tool orchestration.

The candidate workspace has only:
- `target.bin`: stripped x86-64 Linux ELF shared library, with only `command_dispatch` exported.
- `disassembly.txt`: deterministic LLVM/GNU `objdump` disassembly captured from those exact bytes.
- `recovered.json`: the *only* candidate-written file. JSON expression grammar is defined in task.json.

The evaluator checks the expression graph against an independent native-source semantics implementation for four opcode cases × 80 inputs (320 cases). It rejects binary/disassembly mutation and disallows executable code, imports, external calls or arbitrary DSL operations. Parser complexity is explicitly bounded; no actor-supplied Python code is executed.

## Trusted preparer / independent verification

Use the existing source-known reference under `qualification/reference/portable-dispatch-v0`:

```sh
python3 qualification/reference/portable-dispatch-v0/prepare_work_sample.py --destination /tmp/re-dispatch-work-sample
python3 /tmp/re-dispatch-work-sample/verify.py --self-test
```

The *prepared* directory is trusted-side, contains both `fixture` and separately held verifier/manifest, and must not be mounted into the actor workcell wholesale. An existing `qualification/run_task.py` invocation should receive this prepared task directory, which copies only its `fixture` into the candidate workspace. For meaningful blinding, isolate the candidate OS/container permissions against the repo's source and the preparer's verifier/manifest; the generic task-runner's copy semantics **alone do not guarantee OS-level blind isolation**. Do not treat a configured-actor PASS as independent if the actor can read reference source or oracle through a broader filesystem/shell tool.

The committed task directory intentionally includes no binary bytes: preparer generates them from public synthetic C source on the *admitted execution host* and records SHA-256 IDs. `verify.py --self-test` requires the prepared directory and prints SKIP with a zero exit status on the unmaterialized source tree; that is not a verification PASS.

In a clean public GHA Linux runner, invoke the preparer and verifier in one step, then separately execute an already-admitted actor/harness with the frozen `task.json`/fixture and appropriate OS-level confinement. Later replace `disassembly.txt` with a read-only Ghidra-generated evidence projection (staged as qualification/tools/ghidra/ExportREFunctions.java; not yet exercised) on the same exact target, without changing the hidden semantic oracle. Compare source/tool/harness/runtime/model one dimension at a time.

**Evidence / limitations:** Locally prepared and self-tested 2026-10-18 with Clang 17 and LLVM objdump; 1 known-good + 8 negative controls PASS (including undeclared output and symlink checks). The semantic truth source is deliberately simple; no cross-target execution, no model-driven RE, no claims about malware isolation. Other OS/ISA variants require separately qualified runtime and tool projections. No model inference or paid compute is required for this verifier smoke.

## Reproducibility correction — 2026-10-18

Initial disassembly text included an absolute scratch-directory path, so text SHA-256 differed across otherwise identical builds. The preparer now runs the disassembler with `cwd=fixture` and operand `target.bin`, removing the machine-specific path prefix and recording Clang, objdump, and GNU strip version identifiers. Two independent preparation directories on the same execution host produced identical binary and disassembly digests; both independently passed the strengthened verifier. The unmaterialized verifier self-test now emits `SKIP` with process exit 77 (never success). This corrects evidence hygiene, not model inference or Ghidra qualification.
