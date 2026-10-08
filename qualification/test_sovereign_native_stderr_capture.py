from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "qualification" / "Invoke-SovereignTrueNasHarnessPreflight.ps1"
PREFLIGHT = ROOT / "qualification" / "sovereign_truenas_harness_preflight.sh"

def test_launcher_captures_native_stderr_as_data():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "function Invoke-SshCapture" in text
    assert "RedirectStandardError = $true" in text
    assert "ReadToEndAsync()" in text
    assert "Invoke-SshCapture -HostName $TrueNas -RemoteCommand $remoteCommand" in text
    assert "@(& ssh.exe @sshBase $remoteCommand 2>" not in text

def test_preflight_self_contains_local_bin_path():
    text = PREFLIGHT.read_text(encoding="utf-8")
    assert 'export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"' in text
