from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "qualification" / "Invoke-SovereignTrueNasHarnessPreflight.ps1"

def test_launcher_surfaces_sanitized_remote_failure():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "Sanitize-RemoteError" in text
    assert "Sanitized remote stderr tail" in text
    assert "[REDACTED_GITHUB_TOKEN]" in text
    assert "Remote stderr preserved locally" in text
