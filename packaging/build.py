"""Builds the no-install package with PyInstaller.

    pip install ".[dev,window]" pyinstaller
    python packaging/build.py

macOS: dist/PDF Distiller.app (onedir) and dist/PDF-Distiller-macOS.dmg
Windows: dist/PDF Distiller.exe (onefile)

Signing (optional; without it the build is unsigned and systems warn before the first start, see
docs/signing.md). Set in the environment:
  macOS    MACOS_SIGN_IDENTITY   "Developer ID Application: Name (TEAMID)" from the login keychain
           MACOS_NOTARY_PROFILE  a `xcrun notarytool store-credentials` profile, or instead
           APPLE_ID + APPLE_TEAM_ID + APPLE_APP_PASSWORD (app-specific password)
  Windows  WINDOWS_SIGN_PFX + WINDOWS_SIGN_PASSWORD   code-signing certificate (.pfx) and its password
"""
from __future__ import annotations

import os
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
TIMESTAMP_URL = "http://timestamp.digicert.com"


def run(*cmd: str) -> None:
    subprocess.run(list(cmd), check=True)


def sign_mac(path: Path) -> bool:
    """Signs the finished bundle; returns whether it was a Developer ID signature.

    Always needed: PyInstaller signed the bundle before the license files were added, and a changed bundle
    is reported as damaged once downloaded ("a sealed resource is missing or invalid"). Without an identity
    the signature is ad hoc: enough to run on Apple Silicon, not enough for Gatekeeper."""
    ident = os.environ.get("MACOS_SIGN_IDENTITY")
    if ident:
        run("codesign", "--force", "--deep", "--timestamp", "--options", "runtime",
            "--entitlements", str(ROOT / "packaging" / "entitlements.plist"), "--sign", ident, str(path))
    else:
        run("codesign", "--force", "--deep", "--sign", "-", str(path))
    run("codesign", "--verify", "--deep", "--strict", str(path))
    return bool(ident)


def notarize_mac(dmg: Path) -> None:
    profile = os.environ.get("MACOS_NOTARY_PROFILE")
    if profile:
        auth = ["--keychain-profile", profile]
    elif all(os.environ.get(k) for k in ("APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_PASSWORD")):
        auth = ["--apple-id", os.environ["APPLE_ID"], "--team-id", os.environ["APPLE_TEAM_ID"],
                "--password", os.environ["APPLE_APP_PASSWORD"]]
    else:
        print("note: signed but not notarized (no notary credentials); Gatekeeper still warns", file=sys.stderr)
        return
    run("xcrun", "notarytool", "submit", str(dmg), "--wait", *auth)
    run("xcrun", "stapler", "staple", str(dmg))


def signtool() -> str | None:
    found = shutil.which("signtool")
    if found:
        return found
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    tools = sorted(kits.glob("*/x64/signtool.exe")) if kits.is_dir() else []
    return str(tools[-1]) if tools else None


def sign_windows(exe: Path) -> None:
    pfx, password = os.environ.get("WINDOWS_SIGN_PFX"), os.environ.get("WINDOWS_SIGN_PASSWORD")
    if not pfx:
        print("note: unsigned build; Windows SmartScreen warns before the first start", file=sys.stderr)
        return
    tool = signtool()
    if tool is None:
        raise SystemExit("WINDOWS_SIGN_PFX is set but signtool.exe was not found (Windows SDK)")
    run(tool, "sign", "/f", pfx, "/p", password or "", "/fd", "sha256", "/tr", TIMESTAMP_URL, "/td", "sha256", str(exe))
    run(tool, "verify", "/pa", str(exe))


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
        "--add-data", f"{ROOT / 'app' / 'profiles'}{SEP}app/profiles",
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
    for f in (ROOT / "LICENSE", ROOT / "docs" / "THIRD_PARTY_NOTICES.md"):
        shutil.copy(f, target / f.name)
    for dist in DEPS:
        for f in metadata.files(dist) or []:
            if any(k in str(f).lower() for k in ("licen", "copying", "notice")) and not str(f).endswith(".py"):
                dest = target / "licenses" / dist / Path(*f.parts[1:])
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f.locate(), dest)

    if sys.platform == "win32":
        sign_windows(ROOT / "dist" / f"{NAME}.exe")

    if sys.platform == "darwin":
        app = ROOT / "dist" / f"{NAME}.app"
        signed = sign_mac(app)  # after the license files: changing the bundle later breaks the signature
        if not signed:
            print("note: ad-hoc signed only; macOS warns before the first start (docs/signing.md)", file=sys.stderr)
        if shutil.which("hdiutil"):
            dmg = ROOT / "dist" / "PDF-Distiller-macOS.dmg"
            dmg.unlink(missing_ok=True)
            run("hdiutil", "create", "-volname", NAME, "-srcfolder", str(app), "-ov", "-format", "UDZO", str(dmg))
            if signed:
                run("codesign", "--force", "--timestamp", "--sign", os.environ["MACOS_SIGN_IDENTITY"], str(dmg))
                notarize_mac(dmg)


if __name__ == "__main__":
    main()
