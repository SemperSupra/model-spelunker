from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "qualification" / "Invoke-SovereignTrueNasHarnessPreflight.ps1"


def test_windows_launcher_preserves_remote_script_bytes():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "BaseStream.Write($InputBytes, 0, $InputBytes.Length)" in text
    assert "$script | & ssh.exe" not in text
    assert "ReadToEndAsync()" in text
    assert "$remote.Stdout.Trim()" in text
