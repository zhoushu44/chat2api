"""Verify internal symbol imports - check that named imports from internal
modules actually exist as defined symbols."""
from __future__ import annotations

import ast
import importlib.util
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {".venv", "__pycache__", "node_modules", ".git", ".pytest_cache"}


def collect_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files)


MODULE_INDEX: dict[str, Path] = {}


def build_module_index(files: list[Path]) -> None:
    for path in files:
        rel = path.relative_to(ROOT)
        parts = list(rel.parts)
        if path.name == "__init__.py":
            if len(parts) == 1:
                continue
            dotted = ".".join(parts[:-1])
            MODULE_INDEX[dotted] = path
        else:
            stem = path.stem
            dotted = ".".join(parts[:-1] + [stem])
            MODULE_INDEX[dotted] = path


def file_to_dotted(path: Path) -> str | None:
    rel = path.relative_to(ROOT)
    parts = list(rel.parts)
    cur = ROOT
    for part in parts[:-1]:
        cur = cur / part
        if not (cur / "__init__.py").exists():
            return None
    stem = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
    if stem == "__init__":
        return ".".join(parts[:-1]) if len(parts) > 1 else ""
    return ".".join(parts[:-1] + [stem])


def resolve_relative(file_path: Path, level: int, module: str | None) -> str | None:
    rel = file_path.relative_to(ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        pkg_parts = parts[:-1]
    else:
        pkg_parts = parts[:-1]
    if level - 1 > len(pkg_parts):
        return None
    if level == 0:
        base = pkg_parts
    else:
        base = pkg_parts[: -(level - 1)] if level > 1 else pkg_parts
    if module:
        return ".".join(base + [module])
    return ".".join(base)


def get_defined_symbols(target_path: Path) -> set[str]:
    """Get all top-level defined/imported names in a .py file."""
    try:
        src = target_path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        return set()
    defined = set()
    for s in ast.walk(tree):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(s.name)
        elif isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
                elif isinstance(t, ast.Tuple):
                    for el in t.elts:
                        if isinstance(el, ast.Name):
                            defined.add(el.id)
        elif isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
            defined.add(s.target.id)
        elif isinstance(s, ast.Import):
            for a in s.names:
                defined.add(a.asname or a.name.split(".")[0])
        elif isinstance(s, ast.ImportFrom):
            for a in s.names:
                defined.add(a.asname or a.name)
    # __all__
    for s in ast.walk(tree):
        if isinstance(s, ast.Assign):
            for t in s.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    if isinstance(s.value, (ast.List, ast.Tuple)):
                        for el in s.value.elts:
                            if isinstance(el, ast.Constant):
                                defined.add(el.value)
    return defined


problems: list[str] = []
verified: list[str] = []


def check_imports(file_path: Path, tree: ast.Module) -> None:
    rel_str = str(file_path.relative_to(ROOT)).replace("\\", "/")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level
            target_dotted: str | None = None
            if level > 0:
                target_dotted = resolve_relative(file_path, level, module or None)
            else:
                target_dotted = module
            if target_dotted is None:
                continue
            if target_dotted not in MODULE_INDEX:
                continue  # external module - skip
            target_path = MODULE_INDEX[target_dotted]
            if not target_path.is_file():
                # it's a package dir (from package import X) - check __init__.py
                target_file = target_path / "__init__.py"
                if not target_file.exists():
                    continue
                target_path = target_file
            defined = get_defined_symbols(target_path)
            for alias in node.names:
                if alias.name == "*":
                    continue
                if alias.name not in defined:
                    problems.append(
                        f"{rel_str}:{node.lineno}: from {'.' * level}{module} import {alias.name} "
                        f"-> symbol '{alias.name}' NOT defined in {target_dotted} "
                        f"({target_path.relative_to(ROOT)})"
                    )
                else:
                    verified.append(
                        f"{rel_str}:{node.lineno}: from {'.' * level}{module} import {alias.name} OK"
                    )


def main() -> None:
    files = collect_files()
    print(f"Found {len(files)} py files")
    build_module_index(files)
    print(f"Module index: {len(MODULE_INDEX)} entries")

    parsed = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            parsed.append((f, tree))
        except Exception as e:
            print(f"PARSE FAIL {f}: {e}")

    for f, tree in parsed:
        check_imports(f, tree)

    print()
    print("=" * 70)
    print(f"TOTAL SYMBOL PROBLEMS: {len(problems)}")
    print(f"VERIFIED OK: {len(verified)}")
    print("=" * 70)
    for p in problems:
        print(f"  {p}")


if __name__ == "__main__":
    main()
