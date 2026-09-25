#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import cv2
import numpy as np

GEN_REL = Path("src/desktop_ui_cv/dataset/generator.py")
TEST_REL = Path("tests/test_dataset_integrity.py")


def load_generator(root: Path):
    path = root / GEN_REL
    name = f"desktop_ui_cv_dataset_generator_probe_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load generator.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


def configure_probe(mod, resolution: tuple[int, int]):
    def probe():
        w, h = mod.DESKTOP_SIZE
        image = np.zeros((h, w, 3), dtype=np.uint8)
        return mod.GeneratedPage(
            image=image,
            elements=[
                mod.UIElement(
                    2,
                    [100, 90, 200, 120],
                    "button",
                    "UI Probe",
                )
            ],
            ground_truth_texts=[
                {"text": "OCR Probe", "bbox": [50, 60, 100, 20]}
            ],
        )

    mod.GENERATORS = [("probe", probe)]
    mod.TRAIN_SCENES = ["probe"]
    mod.TARGET_RESOLUTIONS = [resolution]
    mod.DPI_SCALES = [1.0]
    mod.WINDOW_STATES = ["active"]
    mod.add_interaction_state = lambda *args, **kwargs: []
    mod.add_noise = lambda image: image
    mod.variation = lambda image: image
    mod.WINE_SOFTNESS = 0


def parse_ocr(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def expected_bbox(bbox: list[int], resolution: tuple[int, int]) -> list[int]:
    sx = 1280.0 / resolution[0]
    sy = 720.0 / resolution[1]
    x, y, w, h = bbox
    return [int(x * sx), int(y * sy), int(w * sx), int(h * sy)]


def run_success_probe(root: Path, resolution: tuple[int, int], seed: int = 17):
    mod = load_generator(root)
    configure_probe(mod, resolution)
    temp = tempfile.TemporaryDirectory()
    out = Path(temp.name)
    (out / "val" / "images").mkdir(parents=True)
    manifest = mod.generate_dataset(str(out), 1, seed=seed, split="train")
    return temp, out, manifest


def independent_checks(root: Path) -> list[str]:
    errors: list[str] = []

    # Actor-owned regression tests are part of the real #22 increment.
    test_path = root / TEST_REL
    if not test_path.is_file() or test_path.stat().st_size < 100:
        errors.append("TESTS_MISSING_OR_TRIVIAL")
    else:
        try:
            compile(test_path.read_text(encoding="utf-8"), str(test_path), "exec")
        except Exception:
            errors.append("TESTS_SYNTAX")
        else:
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root / "src")
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", str(test_path)],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if proc.returncode != 0:
                errors.append("ACTOR_TESTS_FAIL")

    # F-09: no independent validation -> fail closed and no data.yaml.
    try:
        mod = load_generator(root)
        configure_probe(mod, (1600, 900))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            raised = False
            try:
                mod.generate_dataset(str(out), 1, seed=17, split="train")
            except ValueError:
                raised = True
            if not raised:
                errors.append("F09_MISSING_VAL_DID_NOT_FAIL_CLOSED")
            if (out / "data.yaml").exists():
                errors.append("F09_MISLEADING_DATA_YAML_WRITTEN")
    except Exception as exc:
        if not isinstance(exc, ValueError):
            errors.append("F09_PROBE_ERROR")

    # F-09 positive path + F-10 at two non-native resolutions.
    for resolution in ((1600, 900), (1024, 768)):
        temp = None
        try:
            temp, out, manifest = run_success_probe(root, resolution)
            yaml_text = (out / "data.yaml").read_text(encoding="utf-8")
            if "train: train/images" not in yaml_text:
                errors.append(f"F09_TRAIN_REF_{resolution}")
            if "val: val/images" not in yaml_text:
                errors.append(f"F09_VAL_REF_{resolution}")
            if "val: train/images" in yaml_text:
                errors.append(f"F09_ALIAS_{resolution}")

            entries = parse_ocr(out / "ocr_ground_truth.jsonl")
            by_source = {row["source"]: row for row in entries}
            ui = by_source.get("ui_element")
            content = by_source.get("content_text")
            if ui is None or content is None:
                errors.append(f"F10_OCR_ROWS_{resolution}")
            else:
                if ui["bbox"] != expected_bbox([100, 90, 200, 120], resolution):
                    errors.append(f"F10_UI_SCALE_{resolution}")
                if content["bbox"] != expected_bbox([50, 60, 100, 20], resolution):
                    errors.append(f"F10_CONTENT_SCALE_{resolution}")

            label = (out / "train" / "labels" / "000000.txt").read_text(
                encoding="utf-8"
            ).strip().split()
            if len(label) != 5:
                errors.append(f"LABEL_SHAPE_{resolution}")
            else:
                coords = [float(value) for value in label[1:]]
                if not all(0.0 <= value <= 1.0 for value in coords):
                    errors.append(f"LABEL_BOUNDS_{resolution}")
            if manifest.get("split") != "train":
                errors.append(f"MANIFEST_SPLIT_{resolution}")
        except Exception:
            errors.append(f"SUCCESS_PROBE_ERROR_{resolution}")
        finally:
            if temp is not None:
                temp.cleanup()

    # Same seed / same controlled rendering -> equivalent generated artifacts.
    first = second = None
    try:
        first, out1, _ = run_success_probe(root, (1600, 900), seed=23)
        second, out2, _ = run_success_probe(root, (1600, 900), seed=23)
        rels = [
            Path("train/images/000000.png"),
            Path("train/labels/000000.txt"),
            Path("ocr_ground_truth.jsonl"),
            Path("manifest.json"),
        ]
        for rel in rels:
            if (out1 / rel).read_bytes() != (out2 / rel).read_bytes():
                errors.append(f"DETERMINISM_{rel.as_posix()}")
    except Exception:
        errors.append("DETERMINISM_PROBE_ERROR")
    finally:
        if first is not None:
            first.cleanup()
        if second is not None:
            second.cleanup()

    return sorted(set(errors))


def check(root: Path) -> bool:
    return not independent_checks(root)


def self_test() -> int:
    assert expected_bbox([50, 60, 100, 20], (1600, 900)) == [40, 48, 80, 16]
    assert expected_bbox([50, 60, 100, 20], (1024, 768)) == [62, 56, 125, 18]
    print("PASS desktop-ui-cv integrity verifier self-test")
    return 0


def calibrate_baseline(root: Path) -> int:
    errors = independent_checks(root)
    required = {
        "F09_MISSING_VAL_DID_NOT_FAIL_CLOSED",
        "F09_MISLEADING_DATA_YAML_WRITTEN",
        "F10_CONTENT_SCALE_(1600, 900)",
        "F10_CONTENT_SCALE_(1024, 768)",
    }
    # Baseline has no actor-authored regression file too; that is expected here.
    missing = sorted(required - set(errors))
    if missing:
        print("baseline calibration missing expected defects:", missing)
        print("observed:", errors)
        return 1
    print("PASS baseline calibration exposed F-09 and F-10")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) == 3 and sys.argv[1] == "--calibrate-baseline":
        raise SystemExit(calibrate_baseline(Path(sys.argv[2])))
    if len(sys.argv) != 2:
        raise SystemExit(2)
    root = Path(sys.argv[1])
    errors = independent_checks(root)
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    raise SystemExit(0)
