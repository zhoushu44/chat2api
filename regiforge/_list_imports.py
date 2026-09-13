"""List all imports from all project py files, grouped by file."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {".venv", "__pycache__", "node_modules", ".git", ".pytest_cache"}

files = []
for path in ROOT.rglob("*.py"):
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        continue
    files.append(path)

files = sorted(files)
for f in files:
    rel = str(f.relative_to(ROOT)).replace("\\", "/")
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
    except Exception as e:
        print(f"{rel}: PARSE ERROR {e}")
        continue
    imps = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            imps.append(f"  L{node.lineno}: import {names}")
        elif isinstance(node, ast.ImportFrom):
            level = "." * node.level
            names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
            imps.append(f"  L{node.lineno}: from {level}{node.module or ''} import {names}")
    if imps:
        print(f"\n=== {rel} ===")
        for line in imps:
            print(line)
