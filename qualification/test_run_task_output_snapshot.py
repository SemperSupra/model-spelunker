#!/usr/bin/env python3
from pathlib import Path
import json
import tempfile

from qualification.run_task import snapshot_allowed_outputs

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    work=root/"work"
    work.mkdir()
    (work/"method_ir.json").write_text('{"schema_version":1}\n',encoding="utf-8")
    snap=root/"snapshot"
    manifest=snapshot_allowed_outputs(
        work,
        ["method_ir.json","missing.json"],
        snap,
    )
    assert manifest["files"]["method_ir.json"]["present"] is True
    assert manifest["files"]["missing.json"] == {"present":False}
    assert (snap/"method_ir.json").read_text(encoding="utf-8") == '{"schema_version":1}\n'
    stored=json.loads((snap/"snapshot_manifest.json").read_text(encoding="utf-8"))
    assert stored == manifest

print("PASS bounded allowed-output snapshot")
