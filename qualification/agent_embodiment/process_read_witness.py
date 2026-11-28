"""Read-only strace projection for a fixed public synthetic fixture.

Per-thread trace files belong to the traced command tree. Only aggregate
counts leave the local scratch area. This is not adversarially trusted
capture, a completeness guarantee, or guest/hypervisor evidence.
"""
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path

MAX_FILES = 128
MAX_BYTES = 16 * 1024 * 1024
MAX_FILE = 4 * 1024 * 1024
MAX_LINE = 64 * 1024
PATH_RE = re.compile(r'[A-Za-z0-9_./-]+')
SUFFIX_RE = re.compile(r'[1-9][0-9]{0,9}')


def read_owned(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE:
            raise ValueError('invalid trace file')
        data = bytearray()
        while len(data) <= MAX_FILE:
            chunk = os.read(fd, min(65536, MAX_FILE + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        if (len(data) != before.st_size or len(data) > MAX_FILE or
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('trace file changed or exceeded bound')
        return bytes(data)
    finally:
        os.close(fd)


def interval(window):
    if not isinstance(window, list) or len(window) != 2:
        return None
    if any(not isinstance(t, tuple) or len(t) != 2 or
           any(type(v) is not int or v <= 0 for v in t) for t in window):
        return None
    (wall0, mono0), (wall1, mono1) = window
    if not (0 < wall1 - wall0 <= 120_000_000_000 and 0 < mono1 - mono0 <= 120_000_000_000):
        return None
    # Gross clock-discontinuity guard, not a proof of a stable wall clock.
    if abs((wall1 - wall0) - (mono1 - mono0)) > 50_000_000:
        return None
    return wall0, wall1


def inspect_trace(prefix, fixture, window):
    result = dict(source='linux-strace', window_valid=False, trace_valid=False,
                  matching_reads=0, matching_threads=0)
    bounds = interval(window)
    path = str(fixture)
    if bounds is None or not fixture.is_absolute() or not PATH_RE.fullmatch(path):
        return result
    result['window_valid'] = True
    pattern = re.compile(rb'([0-9]{1,12})\.([0-9]{6}) +(?:read|pread64|readv|preadv|preadv2)\([0-9]+<' +
                         re.escape(os.fsencode(path)) + rb'>,.*\) += +([1-9][0-9]*) +<([0-9]{1,9})\.([0-9]{6})>')
    try:
        trace_paths = []
        with os.scandir(prefix.parent) as entries:
            for entry in entries:
                if not entry.name.startswith(prefix.name + '.'):
                    continue
                suffix = entry.name[len(prefix.name) + 1:]
                if not SUFFIX_RE.fullmatch(suffix) or len(trace_paths) >= MAX_FILES:
                    raise ValueError('invalid trace inventory')
                trace_paths.append(Path(entry.path))
        if not trace_paths:
            return result
        total = reads = threads = 0
        for trace in trace_paths:
            raw = read_owned(trace)
            total += len(raw)
            if total > MAX_BYTES or (raw and not raw.endswith(b'\n')):
                raise ValueError('incomplete or excess trace')
            matching = 0
            for line in raw.splitlines():
                if len(line) > MAX_LINE:
                    raise ValueError('excess trace line')
                match = pattern.fullmatch(line)
                if not match:
                    continue
                seconds, micros, _, duration, duration_micros = map(int, match.groups())
                start = (seconds * 1_000_000 + micros) * 1000
                end = start + (duration * 1_000_000 + duration_micros) * 1000 + 2000
                # Conservative microsecond quantization margin at both ends.
                if bounds[0] <= start - 1000 and end <= bounds[1]:
                    matching += 1
            reads += matching
            threads += bool(matching)
        result.update(trace_valid=True, matching_reads=reads, matching_threads=threads)
    except (OSError, ValueError, OverflowError):
        pass
    return result


def process_read_pass(row):
    return (isinstance(row, dict) and row.get('source') == 'linux-strace' and
            row.get('window_valid') is True and row.get('trace_valid') is True and
            type(row.get('matching_reads')) is int and row['matching_reads'] > 0 and
            type(row.get('matching_threads')) is int and 0 < row['matching_threads'] <= row['matching_reads'])


class ProcessReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixture = self.root / 'fixture.txt'
        self.prefix = self.root / 'trace'
        self.trace = self.root / 'trace.123'
        self.window = [(1_000_000_000_000, 1_000_000_000), (1_001_000_000_000, 2_000_000_000)]

    def line(self, stamp='1000.100000', path=None, count=41, duration='0.000010', call='read'):
        return f'{stamp} {call}(17<{path or self.fixture}>, ""..., 4096) = {count} <{duration}>\n'

    def observe(self):
        return inspect_trace(self.prefix, self.fixture, self.window)

    def test_positive_and_multiple_threads(self):
        self.trace.write_text(self.line())
        (self.root / 'trace.124').write_text(self.line(call='pread64'))
        r = self.observe()
        self.assertTrue(process_read_pass(r))
        self.assertEqual((r['matching_reads'], r['matching_threads']), (2, 2))
        self.assertNotIn(str(self.fixture), str(r))

    def test_wrong_path_zero_read_and_time_refused(self):
        for line in (self.line(path=self.fixture.with_suffix('.other')), self.line(count=0),
                     self.line(count=-1), self.line(stamp='999.999999'),
                     self.line(stamp='1001.000000'), self.line(duration='2.000000')):
            with self.subTest(line=line):
                self.trace.write_text(line)
                self.assertFalse(process_read_pass(self.observe()))

    def test_clock_discontinuity_and_missing_trace(self):
        self.assertFalse(process_read_pass(self.observe()))
        self.trace.write_text(self.line())
        self.window[1] = (1_001_000_000_000, 1_100_000_000)
        self.assertFalse(process_read_pass(self.observe()))

    def test_truncated_symlink_or_foreign_inventory(self):
        self.trace.write_text(self.line().rstrip())
        self.assertFalse(process_read_pass(self.observe()))
        self.trace.unlink()
        target = self.root / 'other'
        target.write_text(self.line())
        self.trace.symlink_to(target)
        self.assertFalse(process_read_pass(self.observe()))
        self.trace.unlink()
        self.trace.write_text(self.line())
        (self.root / 'trace.not-a-pid').write_text('')
        self.assertFalse(process_read_pass(self.observe()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
