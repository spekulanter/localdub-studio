"""Build the macOS app (Apple Silicon) into release/:

* LocalDub-Studio-<version>-macOS-arm64.dmg: a disk image with "LocalDub Studio.app"

    uv run python packaging/build_macos.py [--skip-frontend] [--no-dmg]

The app is self-contained: it carries its own Python and every library, so nothing is installed
when it is first opened. It is only ad-hoc signed (no Apple Developer ID), so macOS asks the user
to confirm the first launch; see docs/INSTALL-macOS.md.

Run it on an Apple Silicon Mac (the CI job does): the wheels are chosen for the machine it runs on.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release"
BUILD = ROOT / "build" / "macos"
APP_NAME = "LocalDub Studio"
BUNDLE_ID = "com.localdub.studio"
MIN_MACOS = "14.0"  # the MLX wheels are built for macOS 14 and newer
PYTHON = "3.12"

APP_FILES = ["pyproject.toml", "uv.lock", ".python-version", "README.md", "CHANGELOG.md"]
APP_DOCS = ["docs/LICENSES.md", "docs/QUALITY.md", "docs/INSTALL-macOS.md"]

LAUNCHER = """#!/bin/bash
# LocalDub Studio: starts the Python that lives inside this app.
HERE="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$HERE/Resources/app"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
# A program started from the Dock does not get your shell's PATH: add Homebrew's folders.
export PATH="$HERE/Resources/app/tools:/opt/homebrew/bin:/usr/local/bin:$PATH"
LOGDIR="$HOME/Library/Logs/LocalDub Studio"
mkdir -p "$LOGDIR"
exec "$HERE/Resources/python/bin/python3" -m localdub.desktop >> "$LOGDIR/launch.log" 2>&1
"""

DMG_README = """LocalDub Studio for Apple Silicon Macs

1. Drag "LocalDub Studio" onto the Applications folder.
2. The first time, macOS says it cannot verify the app (it has no Apple Developer ID signature).
   Open it from Applications with a right-click (or Control-click) and choose Open, then Open again.
   If macOS only offers "Move to Bin": open System Settings > Privacy & Security, scroll down and
   press "Open Anyway" next to LocalDub Studio.
3. In the app, open "AI models" and download what it asks for. FFmpeg is one of them.
   Translation needs Ollama (https://ollama.com), which you install yourself.

More: https://github.com/spekulanter/localdub-studio
"""


def run(cmd: list[str | Path], **kw: object) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, text=True, **kw)  # type: ignore[call-overload]  # noqa: S603


def version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def need_uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv was not found on PATH")
    return uv


def copy_python(uv: str, dest: Path) -> Path:
    """A relocatable CPython (python-build-standalone, via uv) copied into the app."""
    install_dir = BUILD / "python-install"
    env = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(install_dir)}
    run([uv, "python", "install", PYTHON, "--managed-python"], env=env)
    found = subprocess.run(  # noqa: S603
        [uv, "python", "find", PYTHON, "--managed-python"], env=env,
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    prefix = Path(found).resolve().parent.parent  # .../bin/python3.12 -> the install prefix
    shutil.copytree(prefix, dest, symlinks=True)
    python = dest / "bin" / "python3"
    if not python.exists():
        raise SystemExit(f"{python} is missing after copying Python from {prefix}")
    return python


def install_libraries(uv: str, python: Path) -> None:
    """Every library from uv.lock (the macOS part), hash-checked, into the app's own Python."""
    BUILD.mkdir(parents=True, exist_ok=True)
    reqs = BUILD / "requirements.txt"
    run([uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--no-header",
         "--output-file", reqs], cwd=ROOT)  # fmt: skip
    # copy, not clone/hardlink: the app must not depend on uv's cache, and two packages that share a
    # folder (sherpa-onnx and sherpa-onnx-core) must both land in it.
    run([uv, "pip", "install", "--python", python, "--break-system-packages", "--require-hashes",
         "--no-deps", "--compile-bytecode", "--link-mode", "copy",
         "-r", reqs], cwd=ROOT)  # fmt: skip


CHECK_RECORDS = """
import sys
from importlib.metadata import distributions

missing = []
for dist in distributions():
    for f in dist.files or []:
        if f.suffix in (".pyc",) or "__pycache__" in f.parts or f.name == "RECORD":
            continue
        if not f.locate().exists():
            missing.append(f"{dist.metadata['Name']}: {f}")
print(f"{len(missing)} files listed by the installed packages are missing")
for m in missing[:40]:
    print("  ", m)
sys.exit(1 if missing else 0)
"""


def check_installed_files(python: Path) -> None:
    """Every file a package says it installed must be there (catches silently dropped files)."""
    run([python, "-I", "-c", CHECK_RECORDS])


def fix_dangling_symlinks(root: Path) -> None:
    """A link that points nowhere makes codesign fail. Python's `etc/openssl/cert.pem` is one:
    point it at certifi's bundle, which the libraries brought along."""
    certifi = next((root / "lib").glob("python3.*/site-packages/certifi/cacert.pem"), None)
    for link in sorted(p for p in root.rglob("*") if p.is_symlink()):
        if link.exists():
            continue
        print("dangling link:", link.relative_to(root), "->", os.readlink(link))
        link.unlink()
        if link.name == "cert.pem" and certifi is not None:
            link.symlink_to(os.path.relpath(certifi, link.parent))


def copy_app_files(app_dir: Path, uv: str) -> None:
    for p in sorted((ROOT / "localdub").rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            target = app_dir / p.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("frontend/dist is missing: build the frontend first")
    shutil.copytree(dist, app_dir / "frontend" / "dist")
    for name in [*APP_FILES, *APP_DOCS]:
        src = ROOT / name
        if src.is_file():
            target = app_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    tools = app_dir / "tools"
    tools.mkdir()
    shutil.copy2(uv, tools / "uv")  # the app uses it to install the optional Demucs packages
    shutil.copy2(ROOT / "packaging" / "THIRD-PARTY-uv.txt", tools / "THIRD-PARTY-uv.txt")
    shutil.copy2(ROOT / "packaging" / "installed-macos.marker", app_dir / ".installed")


def write_bundle(app: Path, ver: str) -> Path:
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    resources = contents / "Resources"
    resources.mkdir()
    launcher = contents / "MacOS" / APP_NAME
    launcher.write_text(LAUNCHER, encoding="utf-8")
    launcher.chmod(0o755)
    shutil.copy2(ROOT / "localdub" / "assets" / "localdub-orange.icns", resources)
    plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": "localdub-orange",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": ver,
        "CFBundleShortVersionString": ver,
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.video",
        "NSHighResolutionCapable": True,
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSHumanReadableCopyright": "MIT licence",
    }
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)
    return resources


def sign(app: Path) -> None:
    """Ad-hoc signature: seals the bundle (no developer identity, so Gatekeeper still asks)."""
    try:
        run(["codesign", "--force", "--deep", "--sign", "-", "--timestamp=none", app])
        run(["codesign", "-vvv", "--deep", "--strict", app])
    except subprocess.CalledProcessError as exc:
        print(f"WARNING: ad-hoc signing failed ({exc}); continuing with an unsealed bundle")
        subprocess.run(["codesign", "-dvvv", str(app)], check=False)  # noqa: S603,S607


def build_dmg(app: Path, ver: str) -> Path:
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run(["ditto", app, stage / app.name])  # keeps symlinks, permissions and signatures
    (stage / "Applications").symlink_to("/Applications")
    (stage / "How to open.txt").write_text(DMG_README, encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    dmg = OUT / f"LocalDub-Studio-{ver}-macOS-arm64.dmg"
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", stage, "-ov", "-format", "UDZO",
         "-fs", "HFS+", dmg])  # fmt: skip
    return dmg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-frontend", action="store_true")
    ap.add_argument("--no-dmg", action="store_true", help="only build the .app")
    args = ap.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise SystemExit("Build the macOS app on an Apple Silicon Mac (or the macOS CI runner).")
    uv = need_uv()
    ver = version()
    if not args.skip_frontend:
        run(["npm", "run", "build"], cwd=ROOT / "frontend")
    shutil.rmtree(BUILD, ignore_errors=True)
    app = BUILD / f"{APP_NAME}.app"
    resources = write_bundle(app, ver)
    python = copy_python(uv, resources / "python")
    install_libraries(uv, python)
    check_installed_files(python)
    fix_dangling_symlinks(resources / "python")
    app_dir = resources / "app"
    copy_app_files(app_dir, uv)
    run([python, "-m", "compileall", "-q", app_dir / "localdub"])
    sign(app)
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1e9
    print(f"{app} is {size:.2f} GB")
    if args.no_dmg:
        return 0
    dmg = build_dmg(app, ver)
    digest = sha256(dmg)
    (dmg.parent / f"{dmg.name}.sha256").write_text(f"{digest}  {dmg.name}\n", encoding="utf-8")
    mb = dmg.stat().st_size / 1e6
    print(f"{dmg.name}  {mb:.1f} MB  sha256 {digest}")
    if dmg.stat().st_size > 1.9 * 1024**3:
        print("WARNING: bigger than 1.9 GiB; GitHub allows 2 GiB per release file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
