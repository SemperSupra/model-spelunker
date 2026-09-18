#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

iverilog -g2012 -s tb -o refsim reference.sv tb.sv
vvp refsim | tee reference.out
grep -qx PASS reference.out
! grep -q '^FAIL' reference.out

iverilog -g2012 -s tb -o badsim known_bad.sv tb.sv
vvp badsim > known_bad.out 2>&1 || true
grep -q '^FAIL' known_bad.out
! grep -qx PASS known_bad.out

printf 'ORACLE_VALIDATED\n'
