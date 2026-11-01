"""Compile the program's Python files to bytecode while Setup still has administrator rights.

The program is installed in Program Files, which the user who runs it cannot write to. Python then
cannot save its compiled files (`__pycache__`) and compiles every library again on every start; on a
test machine that was the difference between about 7 and about 2 seconds before the window opened.
Best effort: a problem here must never fail the installation.
"""

from __future__ import annotations

import compileall
import sys
import sysconfig
from pathlib import Path


def main() -> int:
    app = Path(__file__).resolve().parents[1]  # <install folder>\tools\precompile.py
    paths = sysconfig.get_paths()
    folders = [app / "localdub", Path(paths["stdlib"]), Path(paths["purelib"])]
    ok = True
    for folder in folders:
        if folder.is_dir():
            ok &= bool(compileall.compile_dir(str(folder), quiet=1, workers=0, force=False))
            print(f"compiled {folder}")
    print("bytecode ready" if ok else "bytecode: some files could not be compiled (not a problem)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
