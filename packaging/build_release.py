"""Build the Windows release: a ZIP with the app, built UI and installer scripts, plus a
self-extracting Setup.exe made with Windows' own IExpress.

    uv run python packaging/build_release.py [--skip-frontend] [--no-sfx]

Output goes to release/. The files are unsigned, so Windows SmartScreen will warn on first run.
"""

from __future__ import annotations

import argparse
import hashlib
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


SED = """[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsertLicense=0
RebootMode=N
TargetName={target}
FriendlyName=LocalDub Studio Setup
AppLaunched=cmd /c setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="{zipname}"
FILE1="setup.cmd"
[SourceFiles]
SourceFiles0={outdir}
[SourceFiles0]
%FILE0%=
%FILE1%=
"""

# noqa below: batch lines cannot be wrapped
SETUP_CMD = """@echo off
title LocalDub Studio setup
set "D=%TEMP%\\LocalDubSetup"
if exist "%D%" rmdir /s /q "%D%"
powershell.exe -NoProfile -Command "Expand-Archive -LiteralPath '%~dp0{zipname}' -DestinationPath '%D%' -Force"
for /d %%F in ("%D%\\LocalDub-Studio-*") do powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%%F\\install.ps1"
echo.
pause
"""  # noqa: E501


def build_sfx(ver: str, zip_path: Path) -> Path | None:
    iexpress = Path(r"C:\Windows\System32\iexpress.exe")
    if not iexpress.is_file():
        print("IExpress not found: skipping Setup.exe")
        return None
    target = OUT / f"LocalDub-Studio-{ver}-Setup.exe"
    work = OUT / "_sfx"
    work.mkdir(exist_ok=True)
    (work / "setup.cmd").write_text(SETUP_CMD.format(zipname=zip_path.name), encoding="ascii")
    (work / zip_path.name).write_bytes(zip_path.read_bytes())
    sed = work / "setup.sed"
    sed.write_text(SED.format(target=target, zipname=zip_path.name, outdir=work), encoding="ascii")
    target.unlink(missing_ok=True)
    subprocess.run([str(iexpress), "/N", "/Q", str(sed)], check=True)  # noqa: S603
    return target if target.is_file() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-frontend", action="store_true")
    ap.add_argument("--no-sfx", action="store_true")
    args = ap.parse_args()
    ver = version()
    if not args.skip_frontend:
        build_frontend()
    zip_path = build_zip(ver)
    outputs = [zip_path]
    if not args.no_sfx:
        sfx = build_sfx(ver, zip_path)
        if sfx:
            outputs.append(sfx)
    for p in outputs:
        digest = sha256(p)
        (p.parent / f"{p.name}.sha256").write_text(f"{digest}  {p.name}\n", encoding="utf-8")
        print(f"{p.name}  {p.stat().st_size / 1e6:.1f} MB  sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
