#!/usr/bin/env python3
"""W-4c cheap adversarial test for producer-only COFF optimizer distinction.

Synthetic objects are intentionally not compiled or linked. Native distinctness
still requires the separately admitted Windows experiment and real /O1 /O2 COFF.
"""
import struct
import tempfile
import unittest
from pathlib import Path
from verify_optimizer_distinct import code_sections, fingerprint, verify

def coff(path, body, *, metadata=b"", flags=0x20):
    header = bytearray(20)
    struct.pack_into("<H", header, 0, 0x8664)
    struct.pack_into("<H", header, 2, 1)
    section = bytearray(40)
    section[:5] = b".text"
    struct.pack_into("<II", section, 16, len(body), 60)
    struct.pack_into("<I", section, 36, flags)
    path.write_bytes(bytes(header) + bytes(section) + body + metadata)

class OptimizerOracle(unittest.TestCase):
    def test_machine_code_change_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            coff(root/"crt_static.obj", b"\x90\xc3")
            coff(root/"crt_static_heldout.obj", b"\x31\xc0\xc3")
            result=verify(root)
            self.assertTrue(result["compiled_code_distinct"])
            self.assertFalse(result["auto_name_permitted"])
    def test_metadata_only_does_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            coff(root/"crt_static.obj", b"\x90\xc3", metadata=b"baseline")
            coff(root/"crt_static_heldout.obj", b"\x90\xc3", metadata=b"heldout")
            result=verify(root)
            self.assertFalse(result["compiled_code_distinct"])
            self.assertFalse(result["meaningful_optimizer_holdout_verified"])
    def test_bad_machine_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.obj"
            coff(p,b"\x90\xc3")
            raw=bytearray(p.read_bytes())
            raw[0]=0
            p.write_bytes(raw)
            with self.assertRaises(ValueError):
                code_sections(p)
    def test_no_code_sections_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.obj"
            coff(p,b"\x90\xc3",flags=0)
            with self.assertRaises(ValueError):
                fingerprint(p)
    def test_truncated_section_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.obj"
            coff(p,b"\x90\xc3")
            raw=bytearray(p.read_bytes())
            struct.pack_into("<I",raw,20+16,999999)
            p.write_bytes(raw)
            with self.assertRaises(ValueError):
                code_sections(p)
if __name__=="__main__":
    unittest.main()
