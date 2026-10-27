#!/usr/bin/env bash
# One-shot source-known FID + H2 BSim reference creation. No arbitrary binaries.
set -euo pipefail
: "$RUNNER_TEMP"
: "$GITHUB_WORKSPACE"
repo="$GITHUB_WORKSPACE"
work="$RUNNER_TEMP/re-fid-bsim"
mkdir -p "$work/output" "$work/project" "$work/sigs"
clang -O1 -g -fPIC -shared -fno-stack-protector -fno-ident \
  -Wl,--build-id=none \
  "$repo/qualification/reference/portable-dispatch-v0/dispatcher.c" \
  -o "$work/source_known_reference.so"
clang -O1 -g -fPIC -shared -fno-stack-protector -fno-ident \
  -Wl,--build-id=none \
  "$repo/qualification/reference/portable-dispatch-v0/dispatcher.c" \
  -o "$work/stripped_target.so"
strip --strip-all "$work/stripped_target.so"
test -s "$work/source_known_reference.so"
test -s "$work/stripped_target.so"
nm -a "$work/source_known_reference.so" | grep -q 'handler_fold'
if nm -a "$work/stripped_target.so" 2>/dev/null | grep -q 'handler_fold'; then
  echo 'target wrongly exposes local reference name' >&2; exit 10
fi
ghidra="$work/ghidra_12.1.4_PUBLIC"
if ! test -x "$ghidra/support/analyzeHeadless"; then
  asset="ghidra_12.1.4_PUBLIC_20260921.zip"
  curl --fail --location --silent --show-error --retry 2 --connect-timeout 15 \
    --max-time 270 --output "$work/$asset" \
    "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/$asset"
  printf '%s  %s\n' \
    "ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db" \
    "$work/$asset" | sha256sum --check --status
  (cd "$work" && unzip -q "$asset" && rm -- "$asset")
fi
test -x "$ghidra/support/analyzeHeadless"
java -version
export GHIDRA_HEADLESS_MAXMEM=2G
timeout --signal=TERM 180 "$ghidra/support/analyzeHeadless" \
  "$work/project" "RESourceKnownReference" \
  -import "$work/source_known_reference.so" \
  -max-cpu 2 -analysisTimeoutPerFile 90 \
  -log "$work/output/import.log" -scriptlog "$work/output/import-scripts.log"
timeout --signal=TERM 180 "$ghidra/support/analyzeHeadless" \
  "$work/project" "RESourceKnownReference" \
  -process "source_known_reference.so" \
  -readOnly -noanalysis -max-cpu 2 \
  -scriptPath "$repo/qualification/tools/ghidra" \
  -postScript BuildSourceKnownFid.java "$work/output/source-known.fidb" \
  -log "$work/output/fid.log" -scriptlog "$work/output/fid-scripts.log" \
  | tee "$work/output/fid-stdout.log"
test -s "$work/output/source-known.fidb"
grep -q 'RE_FID_ADDED=' "$work/output/fid-stdout.log"
bsim="$ghidra/support/bsim"
database="file:$work/output/source-known-bsim"
timeout --signal=TERM 90 "$bsim" createdatabase "$database" medium_nosize \
  >"$work/output/bsim-create.log" 2>&1
test -s "$work/output/source-known-bsim.mv.db"
timeout --signal=TERM 180 "$bsim" generatesigs \
  "ghidra:$work/project/RESourceKnownReference" "$work/sigs" --bsim "$database" \
  >"$work/output/bsim-generate.log" 2>&1
timeout --signal=TERM 120 "$bsim" commitsigs "$database" "$work/sigs" \
  >"$work/output/bsim-commit.log" 2>&1
timeout --signal=TERM 90 "$bsim" listfuncs "$database" maxfunc=40 \
  >"$work/output/bsim-functions.log" 2>&1
python3 "$repo/qualification/tools/ghidra/verify_fid_bsim_references.py" "$work"
