#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
iverilog -g2012 -s tb -o refsim reference.sv tb.sv
vvp refsim | tee reference.out
grep -qx PASS reference.out
set +e
iverilog -g2012 -s tb -o badsim known_bad.sv tb.sv
compile_rc=$?
if [ "$compile_rc" -eq 0 ]; then
  vvp badsim > known_bad.out 2>&1
  bad_rc=$?
else
  bad_rc=$compile_rc
fi
set -e
test "$bad_rc" -ne 0
grep -q FAIL known_bad.out || test "$compile_rc" -ne 0
printf 'ORACLE_VALIDATED\n'
