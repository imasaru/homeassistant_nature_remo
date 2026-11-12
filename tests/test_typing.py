"""Enforce strict mypy on the Nature Remo integration (Quality Scale: strict-typing)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_mypy_strict() -> None:
    """Fail if custom_components/nature_remo does not pass mypy --strict."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(ROOT / "mypy.ini"),
            "custom_components/nature_remo",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
