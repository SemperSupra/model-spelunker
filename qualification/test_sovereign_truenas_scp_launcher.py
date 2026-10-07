from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "qualification" / "Invoke-SovereignTrueNasHarnessPreflight.ps1"

def test_launcher_uses_scp_and_native_truenas_gh():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "Require-Command scp.exe" in text
    assert "Stage exact preflight script by SCP" in text
    assert 'PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"' in text
    assert "gh auth status >/dev/null" in text
    assert "$script | & ssh.exe" not in text
    assert "GH_SHIM_LOGIN_FILE" not in text
    assert "GH_SHIM_TOKEN_FILE" not in text
    assert "WriteAllBytes($localScript, $bytes)" in text
