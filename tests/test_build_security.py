from pathlib import Path
import importlib.util
import hashlib
import shutil
import subprocess

import pytest


spec = importlib.util.spec_from_file_location(
    "verify_build_environment", Path(__file__).resolve().parents[1] / "scripts" / "verify_build_environment.py",
)
assert spec and spec.loader
build_environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_environment)


@pytest.mark.parametrize("version", [(3, 11, 5), (3, 11, 16), (3, 12, 13), (3, 12, 14), (3, 13, 0)])
def test_release_rejects_unpatched_or_unsupported_python(version):
    with pytest.raises(RuntimeError, match="CPython"):
        build_environment.verify_python(version)


@pytest.mark.parametrize("version", [(3, 11, 17), (3, 11, 18), (3, 12, 15), (3, 12, 16)])
def test_release_accepts_patched_supported_python(version):
    build_environment.verify_python(version)


def test_release_source_rejects_self_consistent_forged_checksum(tmp_path):
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell is required for the Windows release verifier")
    module = Path(__file__).resolve().parents[1] / "scripts" / "release-sources.ps1"
    expected = hashlib.sha256(b"trusted source").hexdigest()
    forged = hashlib.sha256(b"replaced source").hexdigest()
    script = tmp_path / "check.ps1"
    script.write_text(
        f". '{str(module).replace(chr(39), chr(39)*2)}'\n"
        f"Assert-ReleaseSourcePin -Name source.tar.xz -DeclaredHash {expected} -ExpectedHash {expected}\n"
        f"Assert-ReleaseSourcePin -Name source.tar.xz -DeclaredHash {forged} -ExpectedHash {expected}\n",
        encoding="utf-8",
    )
    completed = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, text=True)
    assert completed.returncode != 0
    assert "trusted release pin" in completed.stderr
