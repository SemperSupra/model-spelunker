"""Bounded local JSON-object stream inspection; never export native payloads."""
import json
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

CAP = 4 * 1024 * 1024
MAX_RECORDS = 2048
EVENTS = ("qwen-code.config", "session.start", "session.end",
          "qwen-code.api_request", "qwen-code.api_response", "qwen-code.api_error",
          "qwen-code.api_cancel", "qwen-code.tool_call", "qwen-code.file_operation")


def unique_object(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError("duplicate JSON key")
        row[key] = value
    return row


def reject_constant(_):
    raise ValueError("nonfinite JSON constant")


def read_capture(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return b""
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > CAP:
            raise ValueError("invalid capture file")
        parts = []
        remaining = CAP + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                break
            parts.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(parts)
        after = os.fstat(fd)
        if len(raw) > CAP or len(raw) != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("capture changed or exceeded bound")
        return raw
    finally:
        os.close(fd)


def inspect_telemetry(path, forbidden):
    raw = read_capture(path)
    data = raw.decode("utf-8")
    decoder = json.JSONDecoder(object_pairs_hook=unique_object, parse_constant=reject_constant)
    counts = dict.fromkeys(EVENTS, 0)
    other = unclassified = pos = count = 0
    marker = any(value.encode() in raw for value in forbidden)
    while pos < len(data):
        while pos < len(data) and data[pos] in " \r\n\t":
            pos += 1
        if pos == len(data):
            break
        row, pos = decoder.raw_decode(data, pos)
        if not isinstance(row, dict) or count >= MAX_RECORDS:
            raise ValueError("invalid or excess capture records")
        count += 1
        # Inspect decoded keys and strings as well as raw bytes. This is a
        # canary check, not a general proof of sensitive-data absence.
        stack = [row]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.keys())
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, str):
                marker = marker or any(x in value for x in forbidden)
        attrs = row.get("attributes")
        event = attrs.get("event.name") if isinstance(attrs, dict) else None
        if isinstance(event, str):
            if event in counts:
                counts[event] += 1
            else:
                other += 1
        else:
            unclassified += 1
    return dict(records=count, bytes=len(raw), payload_marker_seen=marker,
                known_event_counts=counts, other_event_records=other,
                unclassified_records=unclassified)


class CaptureTests(unittest.TestCase):
    def test_native_like_objects_and_no_payload_projection(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "capture"
            p.write_text('{"attributes":{"event.name":"qwen-code.tool_call","secret":"can\\u0061ry"}}\n{"attributes":{"event.name":"private arbitrary label"}}\n{"name":"span"}')
            r = inspect_telemetry(p, ["canary"])
            self.assertEqual((r["records"], r["other_event_records"], r["unclassified_records"]), (3, 1, 1))
            self.assertEqual(r["known_event_counts"]["qwen-code.tool_call"], 1)
            self.assertTrue(r["payload_marker_seen"])
            self.assertNotIn("private arbitrary label", str(r))
            self.assertNotIn("canary", str(r))

    def test_invalid_streams(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "capture"
            for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'[]', b'{"x":', b'\xff', b'{}' * (MAX_RECORDS + 1), b'x' * (CAP + 1)):
                with self.subTest(raw=raw[:24]):
                    p.write_bytes(raw)
                    with self.assertRaises((ValueError, UnicodeError)):
                        inspect_telemetry(p, [])

    def test_nonregular_alias_and_missing(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "capture"
            self.assertEqual(inspect_telemetry(p, ["x"])["records"], 0)
            p.mkdir()
            with self.assertRaises(ValueError):
                inspect_telemetry(p, [])
            p.rmdir()
            target = Path(d) / "target"
            target.write_text('{}')
            p.symlink_to(target)
            with self.assertRaises(OSError):
                inspect_telemetry(p, [])
            p.unlink()
            os.link(target, p)
            with self.assertRaises(ValueError):
                inspect_telemetry(p, [])
            p.unlink()
            os.mkfifo(p)
            with self.assertRaises(ValueError):
                inspect_telemetry(p, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
