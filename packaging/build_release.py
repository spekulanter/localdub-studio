"""Build the Windows release into release/:

* LocalDub-Studio-<version>-Setup.exe: the graphical installer (needs Inno Setup 6)
* LocalDub-Studio-<version>-win64.zip: the same app with PowerShell install scripts (no Inno needed)

    uv run python packaging/build_release.py [--skip-frontend] [--no-installer]

The files are unsigned, so Windows SmartScreen will warn on first run.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release"

TOP_FILES = ["pyproject.toml", "uv.lock", ".python-version", "README.md"]
DOCS = ["docs/LICENSES.md", "docs/QUALITY.md"]
SCRIPTS = ["install.ps1", "launch.ps1", "uninstall.ps1", "Install LocalDub Studio.cmd"]


def version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def build_frontend() -> None:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)  # noqa: S603


def collect() -> list[tuple[Path, str]]:
    """(source file, path inside the package) for everything that ships."""
    files: list[tuple[Path, str]] = []
    for p in sorted((ROOT / "localdub").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            files.append((p, p.relative_to(ROOT).as_posix()))
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("frontend/dist is missing: build the frontend first")
    for p in sorted(dist.rglob("*")):
        if p.is_file():
            files.append((p, p.relative_to(ROOT).as_posix()))
    for name in [*TOP_FILES, *DOCS]:
        files.append((ROOT / name, name))
    for name in SCRIPTS:
        files.append((ROOT / "packaging" / name, name))
    missing = [str(s) for s, _ in files if not s.is_file()]
    if missing:
        raise SystemExit(f"missing files: {missing}")
    return files


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_zip(ver: str) -> Path:
    OUT.mkdir(exist_ok=True)
    folder = f"LocalDub-Studio-{ver}"
    zip_path = OUT / f"{folder}-win64.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/VERSION", ver + "\n")
        for src, rel in collect():
            z.write(src, f"{folder}/{rel}")
    return zip_path


def find_iscc() -> Path | None:
    """The Inno Setup compiler, if installed (winget: JRSoftware.InnoSetup)."""
    candidates = [
        shutil.which("ISCC"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        str(Path.home() / r"AppData\Local\Programs\Inno Setup 6\ISCC.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


def build_installer(ver: str) -> Path | None:
    iscc = find_iscc()
    if iscc is None:
        print(
            "Inno Setup not found: skipping the graphical installer.\n"
            "Install it with: winget install --id JRSoftware.InnoSetup -e"
        )
        return None
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv.exe not found on PATH (it is bundled into the installer)")
    tools = ROOT / "packaging" / "tools"
    tools.mkdir(exist_ok=True)
    shutil.copy2(uv, tools / "uv.exe")
    OUT.mkdir(exist_ok=True)
    subprocess.run(  # noqa: S603
        [str(iscc), f"/DAppVersion={ver}", str(ROOT / "packaging" / "localdub.iss")], check=True
    )
    target = OUT / f"LocalDub-Studio-{ver}-Setup.exe"
    return target if target.is_file() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-frontend", action="store_true")
    ap.add_argument("--no-installer", action="store_true", help="only build the ZIP")
    args = ap.parse_args()
    ver = version()
    if not args.skip_frontend:
        build_frontend()
    zip_path = build_zip(ver)
    outputs = [zip_path]
    if not args.no_installer:
        setup = build_installer(ver)
        if setup:
            outputs.append(setup)
    for p in outputs:
        digest = sha256(p)
        (p.parent / f"{p.name}.sha256").write_text(f"{digest}  {p.name}\n", encoding="utf-8")
        print(f"{p.name}  {p.stat().st_size / 1e6:.1f} MB  sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
