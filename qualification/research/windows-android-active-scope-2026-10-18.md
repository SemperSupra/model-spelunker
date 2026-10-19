# Active RE RDT&E scope: Windows + Android first

**Decision: 2026-10-18.** Owner narrowed the active RDT&E and FID/BSim signature-reuse flywheel to **Windows** and **Android**. This file supersedes the priority ordering (not the observed evidence) in prior platform-wide research notes. No historical research is discarded or represented as newly executed.

## Mission and exclusions

**P0 Windows native:** PE32/PE32+, EXE/DLL/static COFF .lib, Visual C++ v14x and the appropriate **UCRT/VCRuntime/MSVC STL**, clang-cl/lld-link/MinGW as open source comparators, Win32/PDB/CodeView. Delphi/C++Builder **Windows binary** signature recovery can be a later Windows-specific treatment once modern MSVC/CRT reference ingestion is proven; no independent Borland workstream yet.

**P0 Android:** APK/AAB/DEX and compiled native ELF/JNI .so; exact **Android NDK (ARM64 first, x86_64 second)** libc++_static, compiler-rt and unwinder, JNI bridge. Reuse Android Artifact Recovery private #82 / public qualification and device runtime authority #297. Java/Kotlin/R8 metadata/JADX plugin work remains owned by AAR, not a competing general Model Spelunker repository fork.

**Deferred**: macOS/iOS, standalone embedded/router/UEFI firmware, FPGA, other ISA/toolchains, and platform-independent general-purpose signature ingestion. Keep their already cited sources and proofs as a future queue with no active CI spend, scheduled sweep, fresh issue fan-out, or speculative actor-qualification matrix. Windows Delphi/C++Builder is in-scope by *platform* but **not before** initial VC++/NDK task-class acceptance.

## Existing knowledge to consume first

| Domain | Existing identified candidates | Admission/quality note |
| --- | --- | --- |
| Windows FID | Ghidra-bundled Visual Studio FID collections, Ghidra official [Function ID docs](https://github.com/NationalSecurityAgency/ghidra/blob/master/Ghidra/Features/FunctionID/src/main/doc/fid.xml), [NSA ghidra-data](https://github.com/NationalSecurityAgency/ghidra-data), [THREATtrack public .fidb collection](https://github.com/threatrack/ghidra-fidb-repo) | Inspect **installed version + exact FID DB inventory** on pinned Ghidra 12.1.4 *before* building new signatures. Historical Ghidra 9-era community formats require compatibility test. A Windows 10/11 system DLL is not identical to statically linked VC++ CRT library functions. |
| Windows symbol identity | Microsoft public PDB symbol server, PE exported function names and exact PDB GUID+age; source-known VC++/Clang-CL reference builds | Never turn a mere imported DLL function name into an in-binary implementation signature; import .lib may contain only thunks. Symbol licenses and egress rules apply. |
| Android FID | THREATtrack public Android-targeted OpenSSL FID collection for several ISAs; source-known NDK static archives / compiler-built libraries | OpenSSL is **partial**, not comprehensive libc++/NDK coverage. Exact NDK release/ABI and symbol provenance required. |
| Android BSim | Generic Linux/ARM64/x64 public-safe BSim corpora as candidates, Ghidra local H2, provider database/packaging metadata | Cross-ABI matches are hypotheses not identities; install only after license, provenance and quality review. No proven ready-made complete Android NDK BSim DB in census. |
| Actor + runtime | Agent Dispatch #96/#104/#223/#485 + Model Spelunker #139, standard GHA Windows 2025, GHA Ubuntu x64 KVM, synthetic Android API35 emulator, qualified Ghidra 12.1.4 headless and its Java exports | No new executor, no private hosted minutes. Private targets require separately admitted sovereign worker and authorizations. |

## Two parallel, bounded experimental tracks

### W-1 — Windows Visual C++ and system DLL provenance

1. Reconcile live Ghidra 12.1.4 shipped FID installed DB filenames/metadata for Visual Studio versions/architectures. Review selected community FID artifacts and any BSim collections without downloading everything.
2. Build **source-known** Windows PE32+ x64 EXE/DLL and *static code-bearing* COFF library with symbols from existing compiler toolchains, and a matching stripped test. Include exact compiler/runtime tag, linker and CRT linkage, source/binary/PDB digest, provenance and a deliberately absent/near-collision function decoy.
3. Compare no-signature baseline vs packaged FID vs custom FID when the baseline is demonstrably missing source-known code; evaluate FID precision/recall, unrecognized, ambiguous and false identification. BSim local H2 only if a real gap remains after FID, preferably first 1:1 reference/target.
4. Distinguish Windows OS version and system DLL **symbol/build** inventory from compiler static-runtime signatures. Use exact build ID+export/PDB for dynamically linked system DLL functions. Never label OS library implementation as statically embedded code without evidence.
5. Promotion gate: labeled reference function names have independently checked provenance; no proprietary .lib/PDB data or hidden private module content in public GHA.

### A-1 — Android NDK and JNI/DEX correlation

1. Inventory installed or accessible pinned Android NDK archives per ABI and version. Observe symbols/code-bearing members before constructing FID; do not guess that a stripped .so or JNI import stub contains named native implementations.
2. Use prebuilt Android OpenSSL FID as *separate* versioned external-baseline treatment where compatible. Prefer official NDK **libc++_static.a/compiler-rt/unwind** object symbols as labeled reference material. Avoid copying entire archives/signatures into public output without provenance/license review.
3. Create a small public-safe authored Kotlin/Java → JNI → C++ native library fixture for Android ARM64 API35, reuse AAR existing goldens and emulator from Agent Dispatch #297. Include native runtime I/O oracle, JNI method mapping and Android metadata labels, with same-source x86_64 variant second.
4. Compare no-signature native static Ghidra vs FID and/or BSim reference, plus JADX native bridge; preserve AAR optimizer/metadata experiments as independent subtasks.
5. Promotion gate: exact APK/DEX+ELF+NDK/Gradle/ART/ABI identity and held-out behavior oracle; no proprietary APK on public GHA; emulator boot/launch must be qualified for fixture, not inferred from platform census.

## Common minimum receipt and experiment design
For each trial: artifact SHA256 + license/public-safe declaration, producer exact version/source revision/build flags, PE/ELF architecture and ABI, loader/debug metadata, reference DB source+digest+version, tool source/version, target functions/unknowns, verdicts (TP/FP/FN/UNKNOWN), decoys, independent oracle, allowed actor tools, runner admission evidence, CPU/time/artifact volume and recorded failures. **Only one factor changes in each paired A/B comparison**. Scoring a labeled reference corpus does not by itself constitute blind model/agent RE qualification.

### Execution gates / current failure

- Existing Model Spelunker #184 proved Ghidra headless and p-code read-only export on a public-safe x64 ELF. That case remains a **harness calibration**, not a new Linux mission line.
- First FID+BSim *Linux source-known* GHA [run #39109463849](https://github.com/SemperSupra/model-spelunker/actions/runs/39109463849) **FAILED overall after successfully creating FID** (15 attempted, 8 included; BSim CLI exit 22). Do not call BSim qualified. Diagnose precise BSim syntax/invocation on minimal evidence or defer BSim until W-1/A-1 actually need it. Do not continue expanding Linux reference corpus merely to complete a platform-neutral checklist.
- Sidecar caller admission for arbitrary new RE work still unresolved. Repo-native authorized PR CI does not grant arbitrary Agent Dispatch workset rights. No paid provider API or private GHA runners.

## Near-term order

1. **W-0/A-0 discovery:** inventory installed shipped/third-party candidate signatures and exact NDK/MSVC runtime versions and symbol quality, minimal bounded public-safe tool probes.
2. **W-1 Windows first real FID matching** (source-known VC++/Clang-CL PE target, independent false-match controls).
3. **A-1 Android native JNI reference matching** (AAR-owned with model-qualification handoff only).
4. BSim incremental matching on whichever W-1/A-1 baseline has a documented FID shortfall; do not require BSim completion as a prerequisite to starting either track.
5. Then sparse actor configured interviews against the resulting two actual platform families, not broad cross-platform surveys.

All Mac/iOS/firmware/FPGA/Borland-specific deep dives are deferred and should be resumed only by explicit owner reprioritization or a clearly documented dependency from these two active tracks.
