#!/usr/bin/env python3
"""NaabigaCode runner — starts backend server then optional frontend dev server."""

from __future__ import annotations

import argparse
import os
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"


def run_backend(port: int = 8400) -> None:
    # L'import "backend.main" nécessite ROOT (le parent du package backend/)
    # dans sys.path — pas BACKEND_DIR. Sans cela, l'import casse si run.py
    # est exécuté depuis un autre répertoire de travail.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend.main import run_server

    run_server(host="127.0.0.1", port=port)


def run_frontend_dev() -> int:
    cmd = ["npm", "run", "dev", "--", "--host"]
    subprocess.run(cmd, cwd=FRONTEND_DIR, check=False)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="NaabigaCode launcher")
    parser.add_argument("--backend-only", action="store_true", help="run only the backend API")
    parser.add_argument("--frontend-only", action="store_true", help="run only the frontend dev server")
    parser.add_argument("--both", action="store_true", help="run backend then frontend in foreground")
    parser.add_argument("--port", type=int, default=8400, help="backend port")
    args = parser.parse_args()

    if args.frontend_only:
        return run_frontend_dev()

    if args.backend_only:
        run_backend(args.port)
        return 0

    if args.both:
        # In production we'd use a proper process manager; for now, spawn frontend as child.
        frontend = subprocess.Popen(
            ["npm", "run", "dev", "--", "--host"],
            cwd=FRONTEND_DIR,
        )
        try:
            run_backend(args.port)
        finally:
            frontend.terminate()
            frontend.wait()
        return 0

    # default: backend only
    run_backend(args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
