#!/usr/bin/env python3
"""Affine deadcode_scan : les modules chargés DYNAMIQUEMENT ne sont pas morts.

Règles de vie :
- tools/*.py avec registry.register() au niveau module  → vivant (discover_builtin_tools)
- plugins/* avec plugin.yaml                            → vivant (discover_plugins)
- tout module importé statiquement depuis les entrées   → vivant
- tout le reste (orphelin ET non-découvert)             → code mort réel
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRYPOINTS = ["main.py", "agent_bridge.py"]

def module_to_path(mod: str) -> Path | None:
    parts = mod.split(".")
    cand = ROOT.joinpath(*parts).with_suffix(".py")
    if cand.exists():
        return cand
    pkg_init = ROOT.joinpath(*parts) / "__init__.py"
    if pkg_init.exists():
        return pkg_init
    return None

def walk_imports(path: Path, visited: set[Path]) -> None:
    if path in visited:
        return
    visited.add(path)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                r = module_to_path(alias.name)
                if r:
                    walk_imports(r, visited)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                r = module_to_path(node.module)
                if r:
                    walk_imports(r, visited)

def has_top_level_register(path: Path) -> bool:
    """tools/*.py vivant si registry.register(...) au niveau module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            f = node.value.func
            if isinstance(f, ast.Attribute) and f.attr == "register":
                return True
    return False

def main() -> None:
    visited: set[Path] = set()
    for entry in ENTRYPOINTS:
        p = ROOT / entry
        if p.exists():
            walk_imports(p, visited)

    all_py = set()
    for p in ROOT.rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        all_py.add(p)

    # Exclusions : chargés dynamiquement (VIVANTS)
    dynamically_live: set[Path] = set()
    for p in all_py:
        rel = p.relative_to(ROOT)
        parts = rel.parts
        # tools/*.py avec registry.register au top-level
        if parts[0] == "tools" and has_top_level_register(p):
            dynamically_live.add(p)
        # plugins/* avec plugin.yaml dans le même dossier ou un parent
        if "plugins" in parts:
            # cherche plugin.yaml dans le dossier du fichier ou un ancêtre proche
            d = p.parent
            while d != ROOT and "plugins" in d.parts:
                if (d / "plugin.yaml").exists():
                    dynamically_live.add(p)
                    break
                d = d.parent

    orphans = sorted(all_py - visited - dynamically_live, key=lambda p: str(p))
    print(f"Total .py: {len(all_py)}")
    print(f"Statiquement atteignables: {len(visited)}")
    print(f"Chargés dynamiquement (vivants): {len(dynamically_live)}")
    print(f"CODE MORT RÉEL (orphelins non découverts): {len(orphans)}\n")
    for p in orphans:
        print(p.relative_to(ROOT))

if __name__ == "__main__":
    main()
