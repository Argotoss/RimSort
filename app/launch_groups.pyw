"""Windowless launcher for the local Groups edition."""

import os
import runpy
import sys
import tempfile
from pathlib import Path

if __name__ == "__main__":
    project = Path(__file__).resolve().parent.parent
    os.chdir(project)
    sys.path.insert(0, str(project))
    if "--dev" in sys.argv:
        os.environ["RIMSORT_DEV"] = "1"
    if sys.stderr is None:
        sys.stderr = open(
            Path(tempfile.gettempdir()) / "rimsort-groups-launcher.log",
            "a",
            encoding="utf-8",
        )
    if sys.stdout is None:
        sys.stdout = sys.stderr
    runpy.run_module("app", run_name="__main__", alter_sys=True)
