"""Linux inode-scoped file access witness for a bounded synthetic fixture.

The host kernel supplies open/access/close evidence. Inotify does not identify
which process performed the access, nor whether events were coalesced. No raw
file names, contents, paths, or event buffers leave this helper.
"""
import ctypes
import os
import stat
import struct
import tempfile
import unittest
from pathlib import Path


IN_ACCESS = 0x00000001
IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_CLOSE_NOWRITE = 0x00000010
IN_OPEN = 0x00000020
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_UNMOUNT = 0x00002000
IN_Q_OVERFLOW = 0x00004000
IN_IGNORED = 0x00008000
IN_DONT_FOLLOW = 0x02000000
ACCESS = IN_OPEN | IN_ACCESS | IN_CLOSE_NOWRITE
INVALID = IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_DELETE_SELF | IN_MOVE_SELF | IN_UNMOUNT | IN_Q_OVERFLOW | IN_IGNORED
EVENT = struct.Struct('iIII')
MAX_EVENTS = 256


def fingerprint(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('fixture must be a single-link regular file')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class FileAccessWitness:
    def __init__(self, path):
        self.path = Path(path)
        self.before = fingerprint(self.path)
        self.fd = -1
        self.invalid = False
        self.phase = 0
        self.total = 0
        self.early = self.window = self.late = 0
        self.lib = ctypes.CDLL(None, use_errno=True)
        self.lib.inotify_init1.argtypes = [ctypes.c_int]
        self.lib.inotify_init1.restype = ctypes.c_int
        self.lib.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.lib.inotify_add_watch.restype = ctypes.c_int
        self.fd = self.lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), 'inotify init failed')
        try:
            self.wd = self.lib.inotify_add_watch(self.fd, os.fsencode(self.path), ACCESS | INVALID | IN_DONT_FOLLOW)
            if self.wd < 0 or fingerprint(self.path) != self.before:
                raise ValueError('inotify watch not established')
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def drain(self):
        flags = 0
        while True:
            try:
                raw = os.read(self.fd, 4096)
            except BlockingIOError:
                break
            if not raw:
                self.invalid = True
                break
            offset = 0
            while offset < len(raw):
                if len(raw) - offset < EVENT.size:
                    self.invalid = True
                    return flags
                wd, mask, cookie, length = EVENT.unpack_from(raw, offset)
                offset += EVENT.size
                self.total += 1
                if self.total > MAX_EVENTS or length != 0 or wd != self.wd or cookie != 0 or mask & INVALID or mask & ~ACCESS or not mask & ACCESS:
                    self.invalid = True
                    return flags
                flags |= mask
            if self.invalid:
                break
        return flags

    def before_issue(self):
        if self.phase != 0:
            self.invalid = True
            return
        self.early = self.drain()
        self.phase = 1

    def at_result(self):
        if self.phase != 1:
            self.invalid = True
            return
        self.window = self.drain()
        self.phase = 2

    def summary(self):
        self.late = self.drain()
        try:
            unchanged = fingerprint(self.path) == self.before
        except (OSError, ValueError):
            unchanged = False
        return dict(source='linux-inotify', request_result_window_complete=self.phase == 2,
                    open_observed=bool(self.window & IN_OPEN), access_observed=bool(self.window & IN_ACCESS),
                    close_observed=bool(self.window & IN_CLOSE_NOWRITE), pre_window_events=bool(self.early),
                    post_window_events=bool(self.late), file_identity_unchanged=unchanged, observation_invalid=self.invalid)


def witness_pass(row):
    if not isinstance(row, dict) or row.get('source') != 'linux-inotify':
        return False
    return (all(row.get(key) is True for key in ('request_result_window_complete', 'open_observed',
        'access_observed', 'close_observed', 'file_identity_unchanged'))
        and row.get('observation_invalid') is False)


class WitnessTests(unittest.TestCase):
    def test_real_read_in_window(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'fixture'
            p.write_text('synthetic')
            with FileAccessWitness(p) as w:
                w.before_issue()
                self.assertEqual(p.read_text(), 'synthetic')
                w.at_result()
                self.assertTrue(witness_pass(w.summary()))

    def test_outside_window_does_not_qualify(self):
        for treatment in ('none', 'early', 'late', 'open-only'):
            with self.subTest(treatment=treatment), tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'fixture'
                p.write_text('synthetic')
                with FileAccessWitness(p) as w:
                    if treatment == 'early':
                        p.read_bytes()
                    w.before_issue()
                    if treatment == 'open-only':
                        with p.open('rb'):
                            pass
                    w.at_result()
                    if treatment == 'late':
                        p.read_bytes()
                    self.assertFalse(witness_pass(w.summary()))

    def test_changed_inode_or_contents_refused(self):
        for treatment in ('write', 'rename', 'duplicate-result'):
            with self.subTest(treatment=treatment), tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'fixture'
                p.write_text('synthetic')
                with FileAccessWitness(p) as w:
                    w.before_issue()
                    p.read_bytes()
                    if treatment == 'write':
                        p.write_text('changed')
                    elif treatment == 'rename':
                        p.rename(p.with_suffix('.old'))
                        p.write_text('synthetic')
                    w.at_result()
                    if treatment == 'duplicate-result':
                        w.at_result()
                    self.assertFalse(witness_pass(w.summary()))

    def test_invalid_input_and_overflow(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'fixture'
            p.write_text('synthetic')
            alias = p.with_suffix('.alias')
            alias.symlink_to(p)
            with self.assertRaises(ValueError):
                FileAccessWitness(alias)
            with FileAccessWitness(p) as w:
                w.before_issue()
                w.total = MAX_EVENTS
                p.read_bytes()
                w.at_result()
                self.assertFalse(witness_pass(w.summary()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
