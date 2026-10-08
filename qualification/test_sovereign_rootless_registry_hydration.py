from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "qualification" / "sovereign_truenas_harness_preflight.sh"
LAUNCHER = ROOT / "qualification" / "Invoke-SovereignTrueNasHarnessPreflight.ps1"

def test_true_nas_preflight_is_daemonless_and_rootless():
    text = PREFLIGHT.read_text(encoding="utf-8")
    assert "regctl image copy" in text
    assert "ocidir://" in text
    assert "hydrate_oci_layout.py" in text
    assert "REGCTL_VERSION='v0.11.6'" in text
    assert "8e0e62a497fcdb8048d18aa927a139613176ba0531f412bc541044e28f9856bd" in text
    assert "docker pull" not in text
    assert "docker create" not in text
    assert "docker cp" not in text
    assert "docker login" not in text
    assert "sudo " not in text

def test_launcher_stages_exact_hydration_helper():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert '$HelperPath = "qualification/hydrate_oci_layout.py"' in text
    assert "$helperPayload" in text
    assert "WriteAllBytes($localHelper, $helperBytes)" in text
    assert "$localScript,$localHelper,$destination" in text
    assert "rootless regctl -> OCI layout" in text
