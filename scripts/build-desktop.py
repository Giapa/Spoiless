"""Build a local installer without publishing anything. Run from any directory."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd):
    executable = shutil.which(args[0])
    if not executable:
        raise SystemExit(f"Install {args[0]} before building the desktop app.")
    subprocess.run([executable, *args[1:]], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument(
        "--bundles", help="Tauri formats, e.g. deb,appimage or nsis or dmg"
    )
    args = parser.parse_args()
    run(["npm", "ci"], ROOT / "frontend")
    run(["npm", "run", "build"], ROOT / "frontend")
    run(
        [
            "uv",
            "run",
            "--group",
            "desktop",
            "pyinstaller",
            "--noconfirm",
            "--clean",
            "desktop.spec",
        ],
        ROOT / "backend",
    )
    if not args.backend_only:
        run(["npm", "ci"], ROOT / "desktop")
        command = ["npm", "run", "build", "--"]
        if args.bundles:
            command += ["--bundles", args.bundles]
        if sys.platform == "linux":
            # linuxdeploy must resolve the wheel-specific libraries PyInstaller ships.
            libraries = ROOT / "backend/dist/spoiless-backend/_internal"
            directories = sorted(
                {str(path.parent) for path in libraries.rglob("*.so*")}
            )
            existing = os.environ.get("LD_LIBRARY_PATH")
            if existing:
                directories.append(existing)
            os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(directories)
        run(command, ROOT / "desktop")


if __name__ == "__main__":
    main()
