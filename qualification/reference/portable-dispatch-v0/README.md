# Portable source-known dispatcher — cross-object RDT&E control

This tiny freestanding C reference is a **real compiled object corpus**, not merely fabricated magic bytes. It is public-safe and has four distinguishable functions: `handler_affine`, `handler_rotate`, `handler_fold`, and `command_dispatch`. The dispatch input uses three command IDs (0x11, 0x29, 0x3d) and a defined default; the native independent oracle has 16 command/value vectors.

## Reproduce locally or on a standard GHA Linux worker

```sh
python3 qualification/reference/portable-dispatch-v0/build_probe.py
```

Requires Python 3 and a Clang build with the six listed cross-object backends; it does not install tooling or need a platform SDK. `--output <dir>` retains objects locally; by default temporary objects are destroyed. `--no-native` skips the Linux host's shared-library behavior oracle. The default behavior oracle executes **only the generated, source-known Linux library**, never unknown code or foreign target objects.

The same C source is compiled to freestanding objects (not linked applications):

- x86_64 Linux ELF
- aarch64 Linux ELF
- x86_64 Windows COFF
- arm64 macOS Mach-O
- WebAssembly object
- Cortex-M3 ARM ELF

The report distinguishes `PASS`, `COMPILE_FAILED`, `ORACLE_FAILED`, includes source/object SHA-256, compiler identity, expected machine type, and optional native runtime-vectors evidence. **A successful cross-compiled object does not prove native macOS, Windows, Android, iOS, or embedded runtime behavior.** That requires a separately qualified target-specific build/execution environment and independent oracle.

## Verified development observation — 2026-10-18

Clang 17 on a disposable Linux session produced six correctly recognized target objects. The Linux shared-library implementation passed 16 out of 16 independent Python oracle vectors. Source/reference revision is held by the accompanying PR; runner-specific object digests can vary by toolchain and must be remeasured on GHA.

## Next scientific step

Turn the source-known program into frozen object/binary investigation tasks where an actor has only the *compiled artifact* plus a bounded read-only Ghidra/LLVM/LLDB tool projection, not the source or answer-bearing verifier. Keep an external source-known oracle for functions, call edges, and behavior. Perform sparse matched GHA native-vs-Docker crossovers first, then run macOS and Windows native execution treatments after runtime admission. Android NDK and iOS device/Simulator build targets remain separately qualified; never substitute an arbitrary COFF or Mach-O object for a runnable app.

No compiled binaries, secret material, vendor SDKs, or target-derived private data are committed here.
