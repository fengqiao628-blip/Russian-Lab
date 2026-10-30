"""Build a standalone Windows executable and a ZIP for sharing.

Run with the project's virtual-environment Python. --onedir builds a
diagnostic folder first; the default produces the single-file release.
"""

import argparse
import hashlib
from importlib import metadata
from pathlib import Path
import os
import platform
import shutil
import struct
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile


APP_NAME = "铁路运单草单审核助手"
VERSION = "1.0.0"
SOURCE_DIR = Path(__file__).resolve().parent
ROOT = SOURCE_DIR.parent
BUILD_DIR = ROOT / "build"
RELEASE_DIR = ROOT / "release"
RESOURCES_DIR = ROOT / "packaging"


def add_sources(package_dir):
    """Include rebuildable application source, without samples or environments."""
    archive_path = package_dir / "源码与打包脚本.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        archive.write(ROOT / "README.md", "README.md")
        archive.write(ROOT / ".gitignore", ".gitignore")
        for path in sorted(SOURCE_DIR.iterdir()):
            if path.is_file() and (path.suffix in (".py", ".md") or path.name == ".gitignore"
                                   or path.name.startswith("requirements")
                                   or path.name == "windows_version_info.txt"):
                archive.write(path, f"railway_waybill_helper/{path.name}")
        for path in sorted(RESOURCES_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT).as_posix())


def copy_notices(package_dir):
    shutil.copy2(RESOURCES_DIR / "使用说明.txt", package_dir)
    shutil.copy2(RESOURCES_DIR / "第三方组件说明.txt", package_dir)
    licenses_dir = package_dir / "licenses"
    shutil.copytree(RESOURCES_DIR / "licenses", licenses_dir, dirs_exist_ok=True)
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses_dir / "Python-LICENSE.txt")
    for name in ("PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6", "PyInstaller"):
        dist = metadata.distribution(name)
        for entry in dist.files or []:
            if ".dist-info/licenses/" in str(entry).replace("\\", "/"):
                destination = licenses_dir / name / Path(entry).name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dist.locate_file(entry), destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onedir", action="store_true", help="Build a diagnostic folder under build/onedir.")
    parser.add_argument("--console", action="store_true", help="Show diagnostic output; use with --onedir.")
    args = parser.parse_args()
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("Use 64-bit x86 Python on Windows to build this Windows x64 release.")
    try:
        pyinstaller_version = metadata.version("PyInstaller")
    except metadata.PackageNotFoundError:
        parser.error("Install requirements-build.txt with this Python interpreter first.")

    mode = "onedir" if args.onedir else "onefile"
    package_dir = RELEASE_DIR / APP_NAME
    output_dir = BUILD_DIR / "onedir" if args.onedir else package_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--console" if args.console else "--windowed",
        f"--{mode}", "--noupx", "--name", APP_NAME,
        "--distpath", str(output_dir),
        "--workpath", str(BUILD_DIR / mode / "isolated-work"),
        "--specpath", str(BUILD_DIR / mode / "spec"),
        "--version-file", str(SOURCE_DIR / "windows_version_info.txt"),
        "--hidden-import", "PySide6.QtPdf",
        "--paths", str(SOURCE_DIR),
        str(RESOURCES_DIR / "windows_launcher.py"),
    ]
    # Build tools may otherwise pick unrelated DLLs from Git, Poppler, etc.
    # In particular, Qt must use Windows' ICU, not a versioned conda/Poppler ICU.
    build_environment = os.environ.copy()
    windows_dir = Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "C:/Windows")
    if not (windows_dir / "System32").is_dir():
        parser.error("Could not locate the Windows system directory.")
    build_environment["SystemRoot"] = str(windows_dir)
    build_environment["WINDIR"] = str(windows_dir)
    build_environment["PATH"] = os.pathsep.join(str(path) for path in
        (Path(sys.executable).parent, Path(sys.base_prefix), windows_dir / "System32", windows_dir))
    for variable in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        build_environment.pop(variable, None)
    subprocess.run(command, cwd=SOURCE_DIR, env=build_environment, check=True)
    if args.onedir:
        print(f"Diagnostic executable: {output_dir / APP_NAME / (APP_NAME + '.exe')}")
        return 0

    copy_notices(package_dir)
    add_sources(package_dir)
    (package_dir / "版本信息.txt").write_text(
        f"{APP_NAME} {VERSION}\nWindows x64\n"
        f"Python {platform.python_version()}\n"
        f"PySide6 {metadata.version('PySide6')}\n"
        f"PyInstaller {pyinstaller_version}\n",
        encoding="utf-8-sig",
    )
    archive_path = RELEASE_DIR / f"{APP_NAME}_v{VERSION}_Windows_x64.zip"
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(RELEASE_DIR).as_posix())
    executable = package_dir / f"{APP_NAME}.exe"
    checksum_lines = []
    for path in (executable, archive_path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        checksum_lines.append(f"{digest.hexdigest()}  {path.relative_to(RELEASE_DIR).as_posix()}")
    (RELEASE_DIR / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    print(f"Executable: {executable}")
    print(f"Share this ZIP: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
