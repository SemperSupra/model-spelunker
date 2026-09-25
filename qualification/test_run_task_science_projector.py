#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from qualification.run_task import run_science_projector


def test_helper_success_and_ephemeral_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        projector=root/"projector.py"
        output=root/"projection.json"
        projector.write_text(
            """#!/usr/bin/env python3
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("source",type=Path)
p.add_argument("--source-ref",required=True)
p.add_argument("--output",type=Path,required=True)
a=p.parse_args()
raw=a.source.read_text()
assert "PRIVATE_PAYLOAD" in raw
a.output.write_text(json.dumps({"safe":True,"source_ref":a.source_ref})+"\\n")
""",
            encoding="utf-8",
        )
        status=run_science_projector(
            "PRIVATE_PAYLOAD\n",
            projector=projector,
            output=output,
            source_ref="ephemeral:test/source",
        )
        assert status["success"] is True
        assert status["projector_returncode"] == 0
        assert status["output_present"] is True
        assert status["source_deleted"] is True
        assert "PRIVATE_PAYLOAD" not in json.dumps(status)
        projected=json.loads(output.read_text())
        assert projected == {"safe":True,"source_ref":"ephemeral:test/source"}


def test_helper_failure_is_status_not_exception() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        projector=root/"fail.py"
        output=root/"projection.json"
        projector.write_text("raise SystemExit(7)\n",encoding="utf-8")
        status=run_science_projector(
            "sensitive\n",
            projector=projector,
            output=output,
            source_ref="ephemeral:test/failure",
        )
        assert status["success"] is False
        assert status["projector_returncode"] == 7
        assert status["failure_class"] == "projector-nonzero"
        assert status["source_deleted"] is True
        assert not output.exists()


def test_output_inside_workspace_is_rejected_without_raw_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        work=root/"work"
        work.mkdir()
        projector=root/"projector.py"
        projector.write_text("raise SystemExit(0)\n",encoding="utf-8")
        status=run_science_projector(
            "sensitive\n",
            projector=projector,
            output=work/"projection.json",
            source_ref="ephemeral:test/workspace",
            forbidden_root=work,
        )
        assert status["success"] is False
        assert status["failure_class"] == "output-inside-candidate-workspace"
        assert status["source_deleted"] is True
        assert not (work/"projection.json").exists()


def test_existing_projection_output_is_never_deleted_or_overwritten() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        projector=root/"projector.py"
        projector.write_text("raise SystemExit(0)\n",encoding="utf-8")
        output=root/"projection.json"
        output.write_text("KEEP-ME\n",encoding="utf-8")
        status=run_science_projector(
            "sensitive\n",
            projector=projector,
            output=output,
            source_ref="ephemeral:test/existing-output",
        )
        assert status["success"] is False
        assert status["failure_class"] == "projection-output-exists"
        assert status["output_present"] is True
        assert status["source_deleted"] is True
        assert output.read_text(encoding="utf-8") == "KEEP-ME\n"


def test_projector_inside_candidate_workspace_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        work=root/"work"
        work.mkdir()
        projector=work/"candidate_controlled.py"
        projector.write_text("raise SystemExit(0)\n",encoding="utf-8")
        output=root/"projection.json"
        status=run_science_projector(
            "sensitive\n",
            projector=projector,
            output=output,
            source_ref="ephemeral:test/candidate-projector",
            forbidden_root=work,
        )
        assert status["success"] is False
        assert status["failure_class"] == "projector-inside-candidate-workspace"
        assert status["source_deleted"] is True
        assert not output.exists()



def test_run_task_projector_failure_does_not_change_actor_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        task=root/"task"
        fixture=task/"fixture"
        fixture.mkdir(parents=True)
        (fixture/"value.txt").write_text("BROKEN\n",encoding="utf-8")

        verifier=task/"verify.py"
        verifier.write_text(
            """#!/usr/bin/env python3
import sys
from pathlib import Path
value=(Path(sys.argv[1])/"value.txt").read_text()
raise SystemExit(0 if value=="READY\\n" else 1)
""",
            encoding="utf-8",
        )
        (task/"task.json").write_text(
            json.dumps({
                "id":"science-hook-test",
                "task_class":"test",
                "fixture":"fixture",
                "instruction":"Set value.txt to READY.",
                "verifier":"verify.py",
                "allowed_write_paths":["value.txt"],
                "projected_tools":[],
                "limits":{"wall_seconds":10},
            }),
            encoding="utf-8",
        )

        candidate_meta=root/"candidate.json"
        candidate_meta.write_text(
            json.dumps({
                "harness":{"name":"test","version":"1"},
                "model":{"provider":"test","id":"deterministic"},
                "toolset":[],
            }),
            encoding="utf-8",
        )

        projector=root/"fail_projector.py"
        projector.write_text("raise SystemExit(9)\n",encoding="utf-8")
        projection=root/"projection.json"
        receipt=root/"receipt.json"
        runner=Path(__file__).with_name("run_task.py")

        candidate_code=(
            "from pathlib import Path; "
            "Path('value.txt').write_text('READY\\n', encoding='utf-8')"
        )
        proc=subprocess.run(
            [
                sys.executable,
                str(runner),
                "--task-commit","test-commit",
                "--substrate-profile-id","test-substrate",
                "--substrate-profile-commit","test-substrate-commit",
                "--science-projector",str(projector),
                "--science-projection-output",str(projection),
                str(task),
                str(candidate_meta),
                str(receipt),
                "--",
                sys.executable,
                "-c",
                candidate_code,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        recorded=json.loads(receipt.read_text())
        assert recorded["observation"]["success"] is True
        assert recorded["observation"]["verifier_exit_code"] == 0
        assert "science_projection" not in recorded
        assert "MODEL_SPELUNKER_SCIENCE_PROJECTION=" in proc.stdout
        marker=[
            line for line in proc.stdout.splitlines()
            if line.startswith("MODEL_SPELUNKER_SCIENCE_PROJECTION=")
        ][-1]
        status=json.loads(marker.split("=",1)[1])
        assert status["success"] is False
        assert status["projector_returncode"] == 9
        assert status["source_deleted"] is True
        assert not projection.exists()


test_helper_success_and_ephemeral_source()
test_helper_failure_is_status_not_exception()
test_output_inside_workspace_is_rejected_without_raw_file()
test_existing_projection_output_is_never_deleted_or_overwritten()
test_projector_inside_candidate_workspace_is_rejected()
test_run_task_projector_failure_does_not_change_actor_result()

print("PASS optional science projector hook")
