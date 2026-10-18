#!/usr/bin/env bash
# Bounded, public-safe, source-known Ghidra headless qualification.
# Input is a freshly compiled synthetic ELF; no arbitrary binary execution.
set -euo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP required}"
: "${GITHUB_WORKSPACE:?GITHUB_WORKSPACE required}"

fixture="$RUNNER_TEMP/re-probe-a/fixture/target.bin"
test -s "$fixture"
repo="$GITHUB_WORKSPACE"
work="$RUNNER_TEMP/re-ghidra"
mkdir -p "$work/output" "$work/project"
cd "$work"

asset="ghidra_12.1.4_PUBLIC_20260921.zip"
url="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/$asset"
expected="ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db"
curl --fail --location --silent --show-error --retry 2 --connect-timeout 15 --max-time 270 \
  --output "$asset" "$url"
printf '%s  %s\n' "$expected" "$asset" | sha256sum --check --status || {
  echo "GHIDRA_RELEASE_HASH_MISMATCH" >&2
  exit 21
}
unzip -q "$asset"
rm -- "$asset"
test -x ghidra_12.1.4_PUBLIC/support/analyzeHeadless

java -version
export GHIDRA_HEADLESS_MAXMEM=2G
timeout --signal=TERM 240 \
  ghidra_12.1.4_PUBLIC/support/analyzeHeadless \
  "$work/project" "REPublicSynthetic" \
  -import "$fixture" \
  -readOnly -deleteProject -max-cpu 2 -analysisTimeoutPerFile 120 \
  -scriptPath "$repo/qualification/tools/ghidra" \
  -postScript ExportREFunctions.java "$work/output/ghidra-export.json" \
  -postScript ExportRawPcode.java "$work/output/ghidra-pcode.json" \
  -log "$work/output/headless.log" \
  -scriptlog "$work/output/scripts.log"
python3 "$repo/qualification/tools/ghidra/verify_export.py" \
  "$work/output/ghidra-export.json"
python3 "$repo/qualification/tools/ghidra/verify_pcode.py" \
  "$work/output/ghidra-export.json" "$work/output/ghidra-pcode.json"
sha256sum "$work/output/ghidra-export.json" "$work/output/ghidra-pcode.json"
