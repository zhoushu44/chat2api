"""Import analysis tool for RegiForge project.

Walks all .py files (excluding .venv, __pycache__, node_modules, .git),
parses imports with ast, and checks:
  - relative imports correctness (from . / from ..)
  - internal absolute imports (from core.x import y) where path should exist
  - missing __init__.py in packages
  - suspicious import of non-existent symbols in internal modules
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import sysconfig
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {".venv", "__pycache__", "node_modules", ".git", ".pytest_cache"}

# Collect all project .py files
project_py_files: dict[Path, ast.Module] = {}


def collect_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files)


def parse_file(path: Path) -> ast.Module | None:
    try:
        src = path.read_text(encoding="utf-8")
        return ast.parse(src, filename=str(path))
    except SyntaxError as e:
        print(f"[SYNTAX] {path}: {e}")
        return None
    except Exception as e:
        print(f"[READ-ERR] {path}: {e}")
        return None


# ----- module path resolution ----------------------------------------------

# Map of "fully.qualified.module_name" -> Path of the .py file (or package dir)
MODULE_INDEX: dict[str, Path] = {}


def build_module_index(files: list[Path]) -> None:
    """Build an index of all importable modules in the project.

    A directory with __init__.py becomes a package; its dotted path is the
    directory parts joined by '.'.
    A .py file (not __init__) becomes a module; dotted path = dir parts + stem.
    """
    for path in files:
        rel = path.relative_to(ROOT)
        parts = list(rel.parts)
        if path.name == "__init__.py":
            # package - dotted path is the directory parts
            if len(parts) == 1:
                continue  # root __init__.py -> no parent package name
            dotted = ".".join(parts[:-1])
            MODULE_INDEX[dotted] = path.parent
        else:
            stem = path.stem
            dotted = ".".join(parts[:-1] + [stem])
            MODULE_INDEX[dotted] = path


def dir_has_init(d: Path) -> bool:
    return (d / "__init__.py").exists()


# ----- stdlib + site-packages detection ------------------------------------

_STDLIB_PATHS: list[Path] = []
_SITE_PACKAGES_PATHS: list[Path] = []


def init_known_paths() -> None:
    # stdlib
    stdlib_dir = Path(sysconfig.get_paths()["stdlib"])
    purelib = Path(sysconfig.get_paths().get("purelib", stdlib_dir))
    platlib = Path(sysconfig.get_paths().get("platlib", stdlib_dir))
    _STDLIB_PATHS.extend([stdlib_dir, purelib, platlib])
    # site packages from venv
    for p in sys.path:
        if p and "site-packages" in p:
            _SITE_PACKAGES_PATHS.append(Path(p))


def is_external_module(top_name: str) -> bool:
    """True if top_name resolves to a real installed module (stdlib or 3rd-party)."""
    # builtins
    if top_name in sys.builtin_module_names:
        return True
    # try importlib find spec (only top-level)
    spec = importlib.util.find_spec(top_name)
    return spec is not None


# ----- analysis -------------------------------------------------------------

problems: list[str] = []


def file_to_dotted(path: Path) -> str | None:
    """Return the dotted module path of a file relative to ROOT, or None if it
    lives in a directory without __init__.py (i.e. not importable as a package)."""
    rel = path.relative_to(ROOT)
    parts = list(rel.parts)
    # Walk up: every parent dir must have __init__.py for this to be importable
    cur = ROOT
    for i, part in enumerate(parts[:-1]):
        cur = cur / part
        if not (cur / "__init__.py").exists():
            return None
    stem = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
    if stem == "__init__":
        return ".".join(parts[:-1]) if len(parts) > 1 else ""
    return ".".join(parts[:-1] + [stem])


def resolve_relative(file_path: Path, level: int, module: str | None) -> str | None:
    """Resolve a relative import to a dotted name. Returns dotted name or None
    if the resolution is impossible (e.g. file not in a package)."""
    rel = file_path.relative_to(ROOT)
    parts = list(rel.parts)
    # current package: drop the file name; for __init__.py the package is the dir
    if parts[-1] == "__init__.py":
        pkg_parts = parts[:-1]
    else:
        pkg_parts = parts[:-1]
    # need `level` parents
    if level - 1 > len(pkg_parts):
        return None
    if level == 0:
        base = pkg_parts
    else:
        # level=1 -> current package; level=2 -> parent; etc.
        base = pkg_parts[: -(level - 1)] if level > 1 else pkg_parts
    if module:
        return ".".join(base + [module])
    return ".".join(base)


def check_imports(file_path: Path, tree: ast.Module) -> None:
    dotted_self = file_to_dotted(file_path)
    rel = file_path.relative_to(ROOT)
    rel_str = str(rel).replace("\\", "/")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in MODULE_INDEX or top == (dotted_self or "").split(".")[0]:
                    # internal-ish (top-level package matches a project module) -> verify deeper
                    if alias.name in MODULE_INDEX:
                        pass  # OK, file/package exists
                    else:
                        # could be submodule - check if dotted path resolves
                        # if top-level exists in MODULE_INDEX but full doesn't, suspicious
                        if top in MODULE_INDEX:
                            problems.append(
                                f"[import-missing-internal] {rel_str}:{node.lineno}: "
                                f"import {alias.name} (top '{top}' exists but full path not found)"
                            )
                else:
                    if not is_external_module(top):
                        problems.append(
                            f"[import-unresolved] {rel_str}:{node.lineno}: "
                            f"import {alias.name} (top '{top}' not found)"
                        )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level
            if level > 0:
                # relative import
                resolved = resolve_relative(file_path, level, module or None)
                if resolved is None:
                    problems.append(
                        f"[rel-resolve-fail] {rel_str}:{node.lineno}: "
                        f"from {'.' * level}{module} import ... "
                        f"(file not deep enough in package)"
                    )
                    continue
                # Check the resolved module exists as a package or module
                if resolved in MODULE_INDEX:
                    # Now check imported names if it's a module (not package)
                    target_path = MODULE_INDEX[resolved]
                    if target_path.is_file() and target_path.suffix == ".py":
                        # verify names exist as top-level symbols
                        try:
                            tgt_src = target_path.read_text(encoding="utf-8")
                            tgt_tree = ast.parse(tgt_src)
                            defined = set()
                            for s in ast.walk(tgt_tree):
                                if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                  ast.ClassDef)):
                                    defined.add(s.name)
                                elif isinstance(s, ast.Assign):
                                    for t in s.targets:
                                        if isinstance(t, ast.Name):
                                            defined.add(t.id)
                                elif isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
                                    defined.add(s.target.id)
                                elif isinstance(s, ast.Import):
                                    for a in s.names:
                                        defined.add(a.asname or a.name.split(".")[0])
                                elif isinstance(s, ast.ImportFrom):
                                    for a in s.names:
                                        defined.add(a.asname or a.name)
                            # __all__
                            for s in ast.walk(tgt_tree):
                                if isinstance(s, ast.Assign):
                                    for t in s.targets:
                                        if isinstance(t, ast.Name) and t.id == "__all__":
                                            if isinstance(s.value, (ast.List, ast.Tuple)):
                                                for el in s.value.elts:
                                                    if isinstance(el, ast.Constant):
                                                        defined.add(el.value)
                            for alias in node.names:
                                if alias.name == "*":
                                    continue
                                if alias.name not in defined:
                                    problems.append(
                                        f"[rel-symbol-missing] {rel_str}:{node.lineno}: "
                                        f"from {'.' * level}{module} import {alias.name} "
                                        f"(symbol not defined in {resolved})"
                                    )
                        except Exception as e:
                            problems.append(
                                f"[rel-parse-fail] {rel_str}:{node.lineno}: "
                                f"cannot parse target {resolved}: {e}"
                            )
                else:
                    # resolved dotted name not in MODULE_INDEX - maybe it's a
                    # package (dir) without explicit __init__? check dir
                    # actually if it's a package it WOULD be in MODULE_INDEX
                    problems.append(
                        f"[rel-target-missing] {rel_str}:{node.lineno}: "
                        f"from {'.' * level}{module} import ... "
                        f"(resolved '{resolved}' not found as module/package)"
                    )
            else:
                # absolute import
                top = module.split(".")[0]
                if module in MODULE_INDEX:
                    continue  # OK
                if top in MODULE_INDEX:
                    # top-level project package but full path missing
                    problems.append(
                        f"[import-missing-internal] {rel_str}:{node.lineno}: "
                        f"from {module} import ... (top '{top}' exists but full path not found)"
                    )
                else:
                    if not is_external_module(top):
                        problems.append(
                            f"[import-unresolved] {rel_str}:{node.lineno}: "
                            f"from {module} import ... (top '{top}' not found)"
                        )


def main() -> None:
    init_known_paths()
    files = collect_files()
    print(f"Found {len(files)} py files")
    parsed: dict[Path, ast.Module] = {}
    for f in files:
        t = parse_file(f)
        if t is not None:
            parsed[f] = t
            project_py_files[f] = t
    print(f"Parsed {len(parsed)} files")
    build_module_index(files)
    print(f"Built module index: {len(MODULE_INDEX)} entries")

    for f, tree in parsed.items():
        check_imports(f, tree)

    print()
    print("=" * 70)
    print(f"TOTAL PROBLEMS: {len(problems)}")
    print("=" * 70)
    # group by category
    by_cat: dict[str, list[str]] = defaultdict(list)
    for p in problems:
        cat = p.split("]")[0] + "]"
        by_cat[cat].append(p)
    for cat, items in sorted(by_cat.items()):
        print()
        print(f"### {cat} ({len(items)})")
        for it in items:
            print(f"  {it}")


if __name__ == "__main__":
    main()
