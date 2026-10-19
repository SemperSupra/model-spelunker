# Cross-format binary observation triage v0

A **small admission/control task** for evidence discipline before granting an RE actor Ghidra, emulator, debugger, or physical-device access. The eight synthetic, public-safe observations cover PE32+, Mach-O, ELF, APK candidate, IPA candidate, DEX, WASM, and ambiguous firmware-like raw bytes.

The actor can read `observations.json` and write only `classification.json`. It must classify from supplied header and container evidence, attach resolvable JSON pointers, and preserve uncertainty. The verifier executes separately from the candidate workspace, rejects unsupported architecture claims, guessed container validity, fabricated/cross-artifact evidence, and fixture mutation.

This is **not** proof of decompilation, behavioral reconstruction, debugger orchestration, or safe execution. It is a low-cost, platform-neutral precursor for real source-compiled Ghidra/LLDB/JADX/Renode/WinDbg work samples, using existing `qualification/run_task.py` and #139 task/actor contracts. Do not promote placement solely from PASS. No restricted data, target-derived proprietary values, credential, or vendor binary is used.

Self-test: `python3 qualification/tasks/binary-artifact-triage-v0/verify.py --self-test`.

Follow-on: separate source-known real binaries and independently recorded dynamic/semantic oracles for Mach-O, Android DEX/JNI, iOS Simulator, ELF firmware and Windows PE. Preserve actor vs verifier boundaries; freeze and blind new counterfactual variants before qualification.
