import subprocess
import sys


def test_leakage_audit_imports_when_hashlib_is_builtin():
    result = subprocess.run(
        [sys.executable, "-c", "import pipeline.leakage_audit"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
