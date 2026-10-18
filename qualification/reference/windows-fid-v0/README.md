# Windows x64 native MSVC → Ghidra FID control (2026-10-18)

**Execution:** On an admitted standard public GHA `windows-2025` runner, native Visual Studio **18 Enterprise**, **MSVC 14.51.36231**, Windows SDK **10.0.26100.0**, JDK 21 and checksum-verified Ghidra **12.1.4** were exercised. **No proprietary target bytes, user data, secrets or licensed runtime binaries were uploaded.**

## Input and fixture trust

`windows_reference.c` is a public-safe, authored freestanding integer-function fixture. The reference DLL contains five named functions including deliberately unrelated `re_lib_unrelated`. The target DLL has only `re_dispatch` exported, no generated PDB, no helper-name strings, and was built from the *same Microsoft compiler/object* with the same optimizer flags. The code deliberately uses `__declspec(noinline)` under MSVC, so expected helper functions remain independently recognizable. This is a controlled positive treatment, not cross-version portability.

`build_msvc.ps1` uses the installed Visual Studio `VsDevCmd.bat`, `cl.exe`, `link.exe`, `lib.exe` and `dumpbin.exe`; it also counts installed code-bearing MSVC/UCRT libraries separately from Windows SDK import libraries. The independent Python `verify_msvc.py` requires correctly formed x64 PE32+ images, expected reference/target export sets, COFF symbols, source+binary hashes and installed archive categories. It **never executes a PE**. It retains metadata/PDB *only for the named reference*, not the stripped target.

`run_ghidra_fid.ps1` obtains the official pinned Ghidra zip (SHA-256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`), inventories the **shipped** `.fidbf` databases with hashes, analyzes the labeled reference, creates a custom `.fidb`, then opens the stripped PE under a separate process with the reference DB *explicitly attached*. No target renaming/writing. Script `QuerySourceKnownFid.java` reports all candidate names, scores and ambiguity.

## Recorded reproducible evidence

- [First real native MSVC GHA #39116489381](https://github.com/SemperSupra/model-spelunker/actions/runs/39116489381): **PASS** for PE/COFF/PDB/archives and symbol controls; no FID trial yet. Installed: 84 MSVC `.lib` files, 8 UCRT archives, 453 Windows SDK import `.lib` files.
- [First Ghidra FID run #39116711116](https://github.com/SemperSupra/model-spelunker/actions/runs/39116711116): **FAILED** combined acceptance; created reference FID (5/5), but no matches. Methodological correction: explicitly attach the custom reference DB to query process; do not supply a target PDB/debug artifact. Earlier `TARGET_SCANNED=0` name was misleading: it counted *matched candidate rows*, not target functions.
- [Corrected full MSVC→FID GHA #39116979459](https://github.com/SemperSupra/model-spelunker/actions/runs/39116979459): **PASS**, three existing public workflows success. Shipped Ghidra FID count = **10**, 5 source-named reference functions indexed, 4 target functions discovered, **4/4 uniquely identified**, zero ambiguous, zero unrelated-decoy matches. Exact recovered names and scores: `re_dispatch 62.370003`, `re_lib_crc 38.02`, `re_lib_mix 43.010002`, `re_lib_scramble 45.690002`. The reference-only decoy `re_lib_unrelated` was not returned.
- [Retained bounded Windows receipt + shipped FID inventory](https://github.com/SemperSupra/model-spelunker/actions/runs/39116979459/artifacts/12132553404). The native reference/target binaries and PDBs were **not published** in the artifact.
- The **one-shot heavyweight Ghidra/VStudio runner job is intentionally removed from the ordinary PR workflow after qualification** to avoid charging free GHA minutes for unrelated changes. Reuse scripts through the existing admitted typed Agent Dispatch #485 execution path or a separately authorized single-purpose study. No unreviewed generic command interface or workflow-authoring grant.

**Limitations and next rung:** This is same-compiler/same-source controlled matching on four functions, not MSVC CRT/VCRuntime/UCRT coverage, cross-version/different-linker applicability, library matching at production scale, or a configured AI actor interview. FID names are candidates until provenance and an independent executable behavior oracle are checked. Next: classify the ten shipped FID database versions, test MSVC static-library CRT functions under license-safe build conditions with decoys and mismatch controls, then Android NDK ARM64 under AAR ownership. BSim remains `NOT_QUALIFIED` (separate Linux CLI exit-22 failure).

## W-2 installed Microsoft CRT archive source census (2026-10-18)

[Actual `windows-2025` GHA #39118688097](https://github.com/SemperSupra/model-spelunker/actions/runs/39118688097) **PASS**. Same native Visual Studio producer/SDK roots as W-1, no new vendor download, no PE execution, no private input. `inventory_crt_archives.ps1` and stdlib-only `inventory_crt_archives.py` parsed real COFF library archive headers and counted members with populated code (`.text`) sections and the `IMAGE_SCN_CNT_CODE` flag. Results:

| Installed archive | Total members | COFF members with code sections |
| --- | ---: | ---: |
| MSVC `libcmt.lib` | 1193 | 963 |
| MSVC `libcpmt.lib` | 110 | 92 |
| MSVC `libvcruntime.lib` | 63 | 46 |
| MSVC `msvcrt.lib` | 1337 | 963 |
| MSVC `vcruntime.lib` | 116 | 1 |
| UCRT `libucrt.lib` | 787 | 741 |
| UCRT `ucrt.lib` | 1395 | 0 |
| WinSDK `kernel32.lib` | 1401 | 0 |

Bounded metadata-only [GHA artifact #12133596525](https://github.com/SemperSupra/model-spelunker/actions/runs/39118688097/artifacts/12133596525) retains per-archive hashes/size, member counts, <=10 code-member name samples, and section-classification result. Archive bytes, complete vendor symbol tables, PDBs and CRT signatures were **not** uploaded.

**Interpretation:** `libcmt`, `libcpmt`, `libvcruntime`, and `libucrt` have genuine COFF code-bearing members worth evaluating as labeled FID references. `ucrt.lib` and `kernel32.lib` here provide negative import-library-only controls under this parser. Despite its familiar dynamic CRT name, `msvcrt.lib` contains many code-bearing COFF members as well: an archive should **not** be labeled pure import-only based on its filename. These are sections within *archive members*, not unique functions, application runtime proof, or FID recognition rates. An import archive can include code stubs; section counts alone do not establish library code identity. The parser is a bounded diagnostic, not a general COFF archive parser certification.

**Efficiency:** The temporary `windows-crt-archive-one-shot` job was removed from routine PR-triggered qualification CI immediately after the successful observation. Exact parser/source and this evidence remain in draft PR #184. Subsequent cheap workflows must pass independently.

**Next W-3:** choose a small set of actual MSVC/UCRT *code-bearing static* archive members with trustworthy symbols, preserve exact MSVC/SDK/toolchain and archive SHA, independently validate their presence in a **statically linked source-known PE target** (using linker map/PDB only on reference side). Test Ghidra's *shipped* Visual Studio FID signatures first; create new custom FID only for documented missing coverage; require false-positive and absent-library controls. Distinguish a recognized CRT implementation from an API import thunk. BSim remains separate and NOT_QUALIFIED.

## Parallel Android A-0
Under AAR-private #82 and public AAR draft PR #39, [public GHA #39118512769](https://github.com/SemperSupra/android-artifact-recovery/actions/runs/39118512769) **PASS** for installed NDK **27.3.13750724**, ARM64, libc++_static archive 53 members, compiler-rt builtins 279 members, and libunwind not present at tested NDK path. Reference metadata SHA-256 retained in [AAR artifact #12132839720](https://github.com/SemperSupra/android-artifact-recovery/actions/runs/39118512769/artifacts/12132839720), no library bytes uploaded. This is an *inventory only*, not Ghidra FID/native JNI matching. The temporary AAR workflow job was removed. Do not duplicate Android goldens/recovery logic in Model Spelunker.

## W-3a actual CRT linkage provenance: native MSVC /MT versus /MD (2026-10-18)

[Successful public GHA Windows 2025 **#39119408362**](https://github.com/SemperSupra/model-spelunker/actions/runs/39119408362), independent metadata-only [receipt artifact **#12133577825**](https://github.com/SemperSupra/model-spelunker/actions/runs/39119408362/artifacts/12133577825). Source-controlled `windows_crt_consumer.c`, `build_crt_linkage.ps1` and `verify_crt_linkage.py` produce two **nonexecuted** PE32+ x64 images from the same C source, identical optimization and installed Microsoft compiler, changing only `/MT` versus `/MD`. The fixture calls `qsort`, `_strtoui64`, and `strlen`. The independent oracle examines PE headers, `dumpbin /imports` and `/dependents`, and exact linker `/MAP` library-member attribution. No PDB, PE or CRT library is uploaded.

| Factor | MSVC `/MT` | MSVC `/MD` |
| --- | --- | --- |
| Output PE size | **110080** bytes | **10240** bytes |
| Distinct `LIBCMT:object.obj` / `libucrt:object.obj` / `libvcruntime:object.obj` references in linker MAP | **167** | **0** |
| `qsort` present in PE import table | **No** | **Yes** |
| Linked runtime archives observed | LIBCMT.lib, libucrt.lib, libvcruntime.lib | MSVCRT.lib, ucrt.lib, vcruntime.lib |
| Imported system DLL names | KERNEL32.dll | KERNEL32.dll, VCRUNTIME140.dll, UCRT API-set DLLs |

**Failure trace retained rather than discarded:** Initial one-shot [#39119126939](https://github.com/SemperSupra/model-spelunker/actions/runs/39119126939) FAILED the independent provenance oracle because it expected obsolete `Loaded archive(member)` lines from `/VERBOSE:LIB`. Diagnostic rerun [#39119223154](https://github.com/SemperSupra/model-spelunker/actions/runs/39119223154) also FAILED but showed source-grounded MAP entries such as `LIBCMT:utility.obj` and `libucrt:argv_data.obj`; 52 verbose `Searching` lines, no `Loaded` / `Found` lines. Corrected oracle scores the actual Microsoft linker MAP, **not** a guessed verbose grammar. Final [#39119408362](https://github.com/SemperSupra/model-spelunker/actions/runs/39119408362) PASS with distinct static member and dynamic import evidence.

**Scientific limit:** This qualifies **real CRT code inclusion provenance**, not semantic behavior of unexecuted PEs, not named per-function CRT FID matches, not use on unknown binaries, not BSim, and not configured actor improvement. MAP symbol names are trusted *producer evidence*, not accessible to a future blinded actor.

The temporary `windows-crt-linkage-one-shot` job was removed from routine GitHub PR CI immediately after the successful run at cleanup commit `ffde9be524d6275e3c528fa4b4b1a1a4f02c15ac`. Code stays available for admitted narrow one-shot Windows workcells through the existing Agent Dispatch execution system; no new scheduler or default heavyweight CI was created.

**Next W-3b:** Use one of these *actual* source-known `/MT` PEs with verified `libucrt`/`libcmt` member provenance as the target for Ghidra's **shipped Visual Studio FID** reference database, then compare locally produced FID only if packaged coverage is absent. Require independently confirmed library-function identity, calibration against `/MD` import-only negative controls, mismatched CRT version/optimization decoys, and per-function TP/FP/FN/UNKNOWN. Do not score the presence of a library filename as a correct function match. Keep AAR NDK/JNI native RE under #82.

## W-3b built-in Ghidra Visual Studio FID on REAL static MSVC CRT code (2026-10-18)

This experiment advances the reference corpus from custom authored `.fidb` to the **ten Microsoft Visual Studio `.fidbf` files shipped with official Ghidra 12.1.4**, without downloading or generating new vendor signatures.

**Instrument:** Source-known `/MT` and `/MD` PE files from W-3a, each compiled with Microsoft's actual MSVC **14.51**. Windows GHA uses JDK21 and checksum-pinned official Ghidra 12.1.4. The read-only `QueryBundledCrtFid.java` enumerates eligible packaged FID databases and emits bounded best-score candidates; `verify_bundled_crt_fid.py` compares each candidate's exact address/name to producer-side `link.exe /MAP` library/object metadata, kept outside the Ghidra query. No PE is executed, no source/PDB or MAP passed to the signature evaluator, no auto-renaming.

**Packaged Ghidra references observed**: `vs2012_x86/x64`, `vs2015_x86/x64`, `vs2017_x86/x64`, `vs2019_x86/x64`, `vsOlder_x86/x64`; x64 analysis admitted exactly **five** matching-architecture databases. Exact `.fidbf` SHA-256 digests and sizes are recorded in [bounded metadata artifact #12136880097](https://github.com/SemperSupra/model-spelunker/actions/runs/39127085635/artifacts/12136880097).

**Actual matched experimental outcome:** [public standard Windows GHA **#39127085635**](https://github.com/SemperSupra/model-spelunker/actions/runs/39127085635) **SUCCESS** end-to-end, including external MAP oracle.

| Independent metric | `/MT` static CRT | `/MD` dynamically imported CRT |
| --- | ---: | ---: |
| Ghidra analyzed functions | 468 | 99 |
| Candidate FID matches | 82 | 2 |
| Exact candidate name/address agreements with linker CRT labels | 63 | 0 |
| Wrong candidate name at known CRT address | 15 | 0 |
| Unattributed/non-CRT candidate addresses | 4 | 2 |
| Ambiguous candidate rows, best-score ties > 1 | **70** | **2** |
| Known CRT address-bearing MAP symbol rows | 388 | 0 |

**Critical validity warning:** Of 82 static candidates, only **12** had a unique highest-scoring FID candidate; the other **70 were tied**. Even though **63 candidates**' *selected name* exactly agrees with a linker-verified CRT symbol, **this is not 63 independently unique identifications**. Dynamic `/MD` produced two ambiguous `_RTC_Terminate` candidates with no corresponding linker-labelled CRT symbol, demonstrating potential false attribution on import-only controls. Score those `UNKNOWN/AMBIGUOUS`, not successful detection. The independently attributed same-address wrong-name rows are **actual candidate errors**, not random noise. Version mismatch (MSVC 14.51 vs latest shipped Visual Studio 2019 databases) materially limits expected specificity; match scores are not probabilities. A machine count of 82 is not precision.

From the bounded first 60 static candidate records retained in the JSON artifact, **9 have both exact linker CRT name agreement and a unique best-score**. The full run had 12 unique candidates, but the artifact intentionally truncates records after 60; do not assert full-corpus exact-unique counts without another data projection. The [full GitHub Actions execution log](https://github.com/SemperSupra/model-spelunker/actions/runs/39127085635) retains all matched candidate rows and tie counts for review.

**Failure corrections preserved:**
- [First W-3b #39126719132](https://github.com/SemperSupra/model-spelunker/actions/runs/39126719132) FAILED *before Ghidra* because PowerShell `$home` is a read-only automatic variable (case-insensitive); renamed `$ghidraHome`.
- [Second W-3b #39126858630](https://github.com/SemperSupra/model-spelunker/actions/runs/39126858630) successfully invoked both Ghidra queries, observing 82/2 matches, but **failed** the independent oracle due a mistaken parser prefix `RE_SHIPPED_FID_FUNCTIONS_ANALYZED` rather than the actual `RE_FID_FUNCTIONS_ANALYZED`.
- [Corrected #39127085635](https://github.com/SemperSupra/model-spelunker/actions/runs/39127085635) PASSED independent structural and MAP-oracle data collection; no acceptance thresholds reduced to force a result.

**Next gated test W-4:** Freeze two separate consumers: (a) an *assisted analyst* gets only **unique** shipped-FID candidates with source-confirmed reliability evidence from held-out versions; (b) investigate why tied matches are common (identical hashes, parent/child relations, version family collisions) from open Ghidra FID source, before considering BSim or new signature generation. Add deliberate one-bit, optimization, absent-library and import-thunk negatives. No auto-apply of tied FID names.

The one-shot Windows JDK/Ghidra hosted job was **removed from routine PR CI** in `41d1b2fb8aa2a24abcdb76603dd43b0b9005fbbf`. Subsequent cheap standard PR CI **3/3 PASS** (GHA runs 39127406880, 39127406867 and 39127406893). Source and metadata remain on draft PR #184.
