"""Builds the no-install package with PyInstaller.

    pip install -r requirements-dev.txt pyinstaller pywebview
    python packaging/build.py

macOS: dist/PDF Distiller.app (onedir) and dist/PDF-Distiller-macOS.dmg
Windows: dist/PDF Distiller.exe (onefile)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
NAME = "PDF Distiller"
DEPS = ["pikepdf", "pypdfium2", "pillow", "numpy", "fastapi", "starlette", "uvicorn", "python-multipart", "pywebview"]
SEP = ";" if sys.platform == "win32" else ":"


def stamp() -> Path:
    """BUILD file shown in the app header, so a packaged app can be matched to `git log`."""
    def git(*a):
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()
    commit = git("describe", "--always", "--dirty") or "unknown"
    if commit.endswith("-dirty"):
        print("warning: uncommitted changes are being packaged; the app will say so", file=sys.stderr)
    f = ROOT / "build" / "BUILD"
    f.parent.mkdir(exist_ok=True)
    f.write_text(f"{commit} · {datetime.now():%Y-%m-%d %H:%M}\n", "utf-8")
    return f


def main() -> None:
    args = [
        str(ROOT / "run.py"),
        "--name", NAME,
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--add-data", f"{ROOT / 'app' / 'static'}{SEP}app/static",
        "--add-data", f"{ROOT / 'profiles'}{SEP}profiles",
        "--add-data", f"{stamp()}{SEP}.",
        "--collect-submodules", "uvicorn",
        "--collect-all", "pypdfium2_raw",
        "--osx-bundle-identifier", "io.github.pdf-distiller",
        # from app/static/logo.svg via packaging/make_icons.py
        "--icon", str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns")),
    ]
    if sys.platform == "win32":
        args.append("--onefile")
    PyInstaller.__main__.run(args)

    # license texts of bundled libraries must ship with the binary (THIRD_PARTY_NOTICES.md)
    target = ROOT / "dist" / (f"{NAME}.app/Contents/Resources" if sys.platform == "darwin" else "")
    for f in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy(ROOT / f, target / f)
    for dist in DEPS:
        for f in metadata.files(dist) or []:
            if any(k in str(f).lower() for k in ("licen", "copying", "notice")) and not str(f).endswith(".py"):
                dest = target / "licenses" / dist / Path(*f.parts[1:])
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f.locate(), dest)

    if sys.platform == "darwin" and shutil.which("hdiutil"):
        dmg = ROOT / "dist" / "PDF-Distiller-macOS.dmg"
        dmg.unlink(missing_ok=True)
        subprocess.run(["hdiutil", "create", "-volname", NAME, "-srcfolder", str(ROOT / "dist" / f"{NAME}.app"),
                        "-ov", "-format", "UDZO", str(dmg)], check=True)


if __name__ == "__main__":
    main()
