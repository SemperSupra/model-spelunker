"""Native traced vs separate untraced synthetic readers. No model or secrets.

Reuses the existing inode and syscall witnesses. The fixed child program and
separate subprocess launches are trusted fixture construction, not hostile
process containment. Only the bounded aggregate receipt is retained.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from file_access_witness import FileAccessWitness, witness_pass
from process_read_witness import inspect_trace, process_read_pass

READER = """import hashlib, pathlib, sys
if sys.argv[1] == 'read':
    print(hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest())
else:
    print('NO_READ')
"""
CASES = [('target-only', True, False), ('decoy-only', False, True),
         ('neither', False, False), ('both', True, True)]


def run_reader(fixture, reads, expected, prefix=None):
    command = [sys.executable, '-I', '-S', '-B', '-c', READER,
               'read' if reads else 'noop', str(fixture)]
    if prefix is not None:
        command = ['/usr/bin/strace', '-qq', '-ff', '-yy', '-s', '0', '-ttt', '-T',
                   '-e', 'trace=read,pread64,readv,preadv,preadv2',
                   '-o', str(prefix), '--'] + command
    result = subprocess.run(['prlimit', '--fsize=4194304', '--', 'timeout', '-k', '2s', '10s'] + command,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env={'PATH': os.defpath, 'LANG': 'C'}, timeout=15)
    return (result.returncode == 0 and result.stdout ==
            ((expected if reads else 'NO_READ') + '\n').encode('ascii'))


def case_pass(row, target_reads, decoy_reads):
    if row.get('target_exit_oracle') is not True or row.get('decoy_exit_oracle') is not True:
        return False
    inode, trace = row.get('inode'), row.get('trace')
    if not isinstance(inode, dict) or not isinstance(trace, dict):
        return False
    if (inode.get('source') != 'linux-inotify' or inode.get('observation_invalid') is not False or
            inode.get('request_result_window_complete') is not True or
            inode.get('file_identity_unchanged') is not True or
            inode.get('pre_window_events') is not False or inode.get('post_window_events') is not False or
            trace.get('source') != 'linux-strace' or trace.get('trace_valid') is not True or
            trace.get('window_valid') is not True):
        return False
    any_reads = target_reads or decoy_reads
    if not all(inode.get(k) is any_reads for k in ('open_observed', 'access_observed', 'close_observed')):
        return False
    if witness_pass(inode) is not any_reads:
        return False
    if target_reads:
        return process_read_pass(trace)
    return (not process_read_pass(trace) and
            type(trace.get('matching_reads')) is int and trace['matching_reads'] == 0 and
            type(trace.get('matching_threads')) is int and trace['matching_threads'] == 0)


def trial(parent, label, target_reads, decoy_reads):
    with tempfile.TemporaryDirectory(prefix='decoy-', dir=parent) as d:
        root = Path(d).resolve()
        fixture = root / 'fixture.txt'
        payload = secrets.token_bytes(32)
        expected = hashlib.sha256(payload).hexdigest()
        fixture.write_bytes(payload)
        prefix = root / 'trace'
        # Both independently launched commands are bracketed by one observer
        # window. The untraced command never descends from strace or its child.
        gate = threading.Barrier(3, timeout=5)

        def launch(reads, trace_prefix):
            gate.wait()
            return run_reader(fixture, reads, expected, trace_prefix)

        with FileAccessWitness(fixture) as witness, ThreadPoolExecutor(max_workers=2) as pool:
            target = pool.submit(launch, target_reads, prefix)
            decoy = pool.submit(launch, decoy_reads, None)
            witness.before_issue()
            start = (time.time_ns(), time.monotonic_ns())
            gate.wait()
            target_ok = target.result(timeout=20)
            decoy_ok = decoy.result(timeout=20)
            end = (time.time_ns(), time.monotonic_ns())
            witness.at_result()
            row = dict(treatment=label, target_exit_oracle=target_ok, decoy_exit_oracle=decoy_ok,
                       inode=witness.summary(), trace=inspect_trace(prefix, fixture, [start, end]))
            row['passed'] = case_pass(row, target_reads, decoy_reads)
            return row


def main(output):
    if os.geteuid() == 0 or not Path('/usr/bin/strace').is_file():
        raise ValueError('non-root native strace fixture required')
    if not output.parent.is_dir() or output.exists():
        raise ValueError('invalid owned receipt path')
    rows = []
    for repetition in range(2):
        for label, target, decoy in CASES:
            try:
                row = trial(output.parent, label, target, decoy)
            except Exception as exc:
                row = dict(treatment=label, passed=False, error=type(exc).__name__)
            row['repetition'] = repetition
            rows.append(row)
    good = len(rows) == 8 and all(r.get('passed') is True for r in rows)
    receipt = dict(schema='synthetic-traced-decoy/v1', source=os.environ.get('GITHUB_SHA', 'UNKNOWN'),
                   raw_trace_retained=False, rows=rows, verdict='PASS' if good else 'FAIL')
    with output.open('x') as f:
        f.write(json.dumps(receipt, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))
    return 0 if good else 1


class DecoyContractTests(unittest.TestCase):
    def test_real_untraced_child_oracle(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = Path(d) / 'fixture'
            fixture.write_bytes(b'public synthetic')
            expected = hashlib.sha256(b'public synthetic').hexdigest()
            self.assertTrue(run_reader(fixture, True, expected))
            self.assertFalse(run_reader(fixture, True, '0' * 64))
            fixture.unlink()
            self.assertTrue(run_reader(fixture, False, expected))
            self.assertFalse(run_reader(fixture, True, expected))

    def test_strict_gate_all_four_cases(self):
        for label, target, decoy in CASES:
            any_reads = target or decoy
            row = dict(target_exit_oracle=True, decoy_exit_oracle=True,
                       inode=dict(source='linux-inotify', observation_invalid=False,
                                  request_result_window_complete=True, file_identity_unchanged=True,
                                  pre_window_events=False, post_window_events=False,
                                  open_observed=any_reads, access_observed=any_reads, close_observed=any_reads),
                       trace=dict(source='linux-strace', trace_valid=True, window_valid=True,
                                  matching_reads=int(target), matching_threads=int(target)))
            with self.subTest(label=label):
                self.assertTrue(case_pass(row, target, decoy))
                self.assertFalse(case_pass(dict(row, target_exit_oracle=False), target, decoy))
                self.assertFalse(case_pass(dict(row, trace=dict(row['trace'], trace_valid=False)), target, decoy))
                self.assertFalse(case_pass(dict(row, inode=dict(row['inode'], observation_invalid=True)), target, decoy))
                self.assertFalse(case_pass(dict(row, trace=dict(row['trace'], matching_reads=int(not target),
                                                               matching_threads=int(not target))), target, decoy))
                self.assertFalse(case_pass(dict(row, inode=dict(row['inode'], access_observed=not any_reads)), target, decoy))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.self_test:
        unittest.main(argv=[__file__], verbosity=2)
    if args.receipt is None:
        parser.error('receipt required')
    raise SystemExit(main(args.receipt.resolve()))
