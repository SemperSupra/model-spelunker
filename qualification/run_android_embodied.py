#!/usr/bin/env python3
"""Run one calibrated Android embodied qualification against a disposable GHA emulator."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

PKGS = ["emulator", "system-images;android-35;google_apis;x86_64"]


def run(argv: list[str], *, timeout: int = 60, env=None, stdin: str | None = None):
    try:
        cp = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            input=stdin,
        )
        return cp.returncode, cp.stdout.strip(), cp.stderr.strip()
    except subprocess.TimeoutExpired:
        return None, "", f"timeout after {timeout}s"


def adb_cmd(adb: Path, serial: str, *args: str, env=None, timeout: int = 20):
    return run(["sudo", "-n", str(adb), "-s", serial, *args], timeout=timeout, env=env)


def reset_task_state(adb: Path, serial: str, *, env) -> None:
    commands = [
        ("shell", "settings", "put", "secure", "user_setup_complete", "1"),
        ("shell", "settings", "put", "global", "device_provisioned", "1"),
        ("shell", "settings", "put", "system", "time_12_24", "12"),
        ("shell", "am", "force-stop", "com.android.settings"),
        ("shell", "am", "start", "-a", "android.settings.SETTINGS"),
    ]
    for command in commands:
        code, out, err = adb_cmd(adb, serial, *command, env=env)
        if code != 0:
            raise RuntimeError(f"task reset failed for {command}: {err[-500:]}")
    time.sleep(1.0)
    code, out, err = adb_cmd(adb, serial, "shell", "settings", "get", "system", "time_12_24", env=env)
    if code != 0 or out.strip() != "12":
        raise RuntimeError(f"initial 12-hour setting not established: rc={code} value={out!r} err={err!r}")


def invoke_task(
    *,
    repo_root: Path,
    task_dir: Path,
    task_commit: str,
    substrate_profile_id: str,
    substrate_profile_commit: str,
    candidate_meta: Path,
    receipt: Path,
    command: list[str],
    env: dict[str, str],
) -> int:
    argv = [
        sys.executable,
        str(repo_root / "qualification" / "run_task.py"),
        "--task-commit",
        task_commit,
        "--substrate-profile-id",
        substrate_profile_id,
        "--substrate-profile-commit",
        substrate_profile_commit,
        str(task_dir),
        str(candidate_meta),
        str(receipt),
        "--",
        *command,
    ]
    cp = subprocess.run(argv, check=False, text=True, env=env)
    return cp.returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task-dir", type=Path, required=True)
    p.add_argument("--task-commit", required=True)
    p.add_argument("--substrate-profile-id", required=True)
    p.add_argument("--substrate-profile-commit", required=True)
    p.add_argument("--candidate-meta", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    p.add_argument("--reference-receipt", type=Path, required=True)
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        p.error("candidate command required after --")

    repo_root = Path(__file__).resolve().parents[1]
    task_dir = args.task_dir.resolve()
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.reference_receipt.parent.mkdir(parents=True, exist_ok=True)

    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("Android embodied qualification requires Linux x86_64")

    sdk = Path(os.environ.get("ANDROID_HOME") or "/usr/local/lib/android/sdk")
    sdkmanager = sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    avdmanager = sdk / "cmdline-tools" / "latest" / "bin" / "avdmanager"
    adb = sdk / "platform-tools" / "adb"
    if not all(x.exists() for x in (sdkmanager, avdmanager, adb)) or not shutil.which("sudo"):
        raise SystemExit("preinstalled Android SDK management entry gate failed")

    install_start = time.monotonic()
    code, out, err = run(
        ["sudo", "-n", str(sdkmanager), "--install", *PKGS],
        timeout=360,
        stdin="y\n" * 200,
    )
    print(
        "ANDROID_EMULATOR_INSTALL="
        + json.dumps(
            {
                "exit_code": code,
                "elapsed_seconds": round(time.monotonic() - install_start, 3),
                "stdout_tail": out[-800:],
                "stderr_tail": err[-800:],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    emulator = sdk / "emulator" / "emulator"
    image = sdk / "system-images" / "android-35" / "google_apis" / "x86_64"
    if code != 0 or not emulator.exists() or not image.is_dir():
        raise SystemExit("bounded emulator/system-image installation failed")

    with tempfile.TemporaryDirectory(prefix="model-spelunker-android-", ignore_cleanup_errors=True) as td:
        root = Path(td)
        avd_home = root / "avd"
        home = root / "home"
        android_user_home = root / "android-home"
        avd_home.mkdir(); home.mkdir(); android_user_home.mkdir()
        env = dict(os.environ)
        env.update(
            {
                "ANDROID_AVD_HOME": str(avd_home),
                "ANDROID_USER_HOME": str(android_user_home),
                "HOME": str(home),
            }
        )
        create_code, _, create_err = run(
            [
                str(avdmanager), "create", "avd", "--force", "--name", "mobqual",
                "--package", PKGS[1], "--device", "pixel_6",
            ],
            timeout=30,
            env=env,
            stdin="no\n",
        )
        if create_code != 0:
            raise SystemExit(f"AVD creation failed: {create_err[-800:]}")

        accel_code, accel_out, accel_err = run(
            ["sudo", "-n", str(emulator), "-accel-check"], timeout=20, env=env
        )
        if accel_code != 0:
            raise SystemExit(f"KVM acceleration unavailable: {(accel_out + accel_err)[-800:]}")

        task_cfg = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        locale = str(task_cfg.get("locale") or "").strip()
        cmd = [
            "sudo", "-n", "env",
            f"ANDROID_AVD_HOME={avd_home}",
            f"ANDROID_USER_HOME={android_user_home}",
            f"HOME={home}",
            str(emulator), "-avd", "mobqual", "-no-window", "-no-audio", "-no-boot-anim",
            "-no-snapshot-load", "-no-snapshot-save", "-accel", "on",
            "-gpu", "swiftshader_indirect", "-no-metrics",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, env=env)
        serial = None
        boot_start = time.monotonic()
        try:
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                c, devices, _ = run(["sudo", "-n", str(adb), "devices"], timeout=10, env=env)
                if c == 0:
                    for line in devices.splitlines():
                        if line.startswith("emulator-") and "\tdevice" in line:
                            serial = line.split("\t", 1)[0]
                            break
                if serial or proc.poll() is not None:
                    break
                time.sleep(2)
            if not serial:
                raise RuntimeError("emulator serial did not become ready")
            while time.monotonic() < deadline:
                c, booted, _ = adb_cmd(adb, serial, "shell", "getprop", "sys.boot_completed", env=env)
                if c == 0 and booted.strip() == "1":
                    break
                time.sleep(2)
            else:
                raise RuntimeError("emulator did not reach sys.boot_completed=1")

            print(
                "ANDROID_EMULATOR_READY="
                + json.dumps(
                    {"serial": serial, "boot_seconds": round(time.monotonic() - boot_start, 3)},
                    sort_keys=True,
                ),
                flush=True,
            )
            qual_env = dict(env)
            qual_env.update(
                {
                    "MODEL_SPELUNKER_ADB_BIN": str(adb),
                    "MODEL_SPELUNKER_ANDROID_SERIAL": serial,
                    "MODEL_SPELUNKER_ANDROID_USE_SUDO": "1",
                    "MODEL_SPELUNKER_TASK_LOCALE": locale,
                }
            )
            if locale:
                c, root_out, root_err = adb_cmd(adb, serial, "root", env=env, timeout=20)
                if c != 0:
                    raise RuntimeError(f"adb root required for locale treatment failed: {root_err[-300:]!r}")
                time.sleep(1.0)
                c, _, locale_err = adb_cmd(
                    adb, serial, "shell",
                    f"setprop persist.sys.locale {locale}; stop; sleep 5; start",
                    env=env, timeout=20,
                )
                if c != 0:
                    raise RuntimeError(f"locale restart command failed: {locale_err[-300:]!r}")
                locale_deadline = time.monotonic() + 90
                while time.monotonic() < locale_deadline:
                    c, booted, _ = adb_cmd(
                        adb, serial, "shell", "getprop", "sys.boot_completed", env=env
                    )
                    if c == 0 and booted.strip() == "1":
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError("locale restart did not return to boot-complete")
                c, observed_locale, locale_err = adb_cmd(
                    adb, serial, "shell", "getprop", "persist.sys.locale", env=env
                )
                if c != 0 or observed_locale.strip() != locale:
                    raise RuntimeError(
                        f"requested locale not established: requested={locale!r} observed={observed_locale!r} err={locale_err[-300:]!r}"
                    )
                print(
                    "ANDROID_LOCALE="
                    + json.dumps({"requested": locale, "observed": observed_locale.strip()}, sort_keys=True),
                    flush=True,
                )

            reset_task_state(adb, serial, env=env)
            reference_meta = root / "reference-candidate.json"
            reference_meta.write_text(
                json.dumps(
                    {
                        "harness": {"name": "deterministic-mobile-reference", "version": "v1"},
                        "model": {"provider": "none", "id": "reference-policy", "treatment_kind": "deterministic"},
                        "toolset": ["mobile_observe_ui", "mobile_tap", "mobile_swipe", "mobile_launch_settings"],
                        "configuration": {"purpose": "task-calibration-only"},
                    },
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            reference_env = dict(qual_env)
            reference_env["MODEL_SPELUNKER_PUBLIC_DIAGNOSTICS"] = "1"
            ref_rc = invoke_task(
                repo_root=repo_root,
                task_dir=task_dir,
                task_commit=args.task_commit,
                substrate_profile_id=args.substrate_profile_id,
                substrate_profile_commit=args.substrate_profile_commit,
                candidate_meta=reference_meta,
                receipt=args.reference_receipt.resolve(),
                command=[sys.executable, str(repo_root / "qualification" / "adapters" / "android_reference_actor.py")],
                env=reference_env,
            )
            ref_receipt = json.loads(args.reference_receipt.read_text(encoding="utf-8"))
            if ref_rc != 0 or ref_receipt.get("observation", {}).get("success") is not True:
                print("ANDROID_REFERENCE_CALIBRATION=FAIL", flush=True)
                return 3
            print("ANDROID_REFERENCE_CALIBRATION=PASS", flush=True)

            reset_task_state(adb, serial, env=env)
            candidate_rc = invoke_task(
                repo_root=repo_root,
                task_dir=task_dir,
                task_commit=args.task_commit,
                substrate_profile_id=args.substrate_profile_id,
                substrate_profile_commit=args.substrate_profile_commit,
                candidate_meta=args.candidate_meta.resolve(),
                receipt=args.receipt.resolve(),
                command=command,
                env=qual_env,
            )
            return candidate_rc
        finally:
            if serial:
                adb_cmd(adb, serial, "emu", "kill", env=env, timeout=15)
            try:
                proc.terminate(); proc.wait(timeout=8)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            run(["sudo", "-n", str(adb), "kill-server"], timeout=10, env=env)
            run(["sudo", "-n", "rm", "-rf", str(avd_home), str(android_user_home), str(home)], timeout=20, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
