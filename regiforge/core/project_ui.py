from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import ROOT

WEB_PROVIDERS_UI = ROOT / "web" / "ui" / "providers.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_provider_ui_schema() -> dict[str, Any]:
    data = _read_json(WEB_PROVIDERS_UI)
    if not data:
        return {"version": 1, "groups": []}
    return data


def load_project_ui(project_id: str) -> dict[str, Any]:
    """读取 projects/<id>/ui/schema.json（项目规划），供 Web 壳渲染。"""
    base = ROOT / "projects" / project_id / "ui"
    schema_path = base / "schema.json"
    schema = _read_json(schema_path)
    if not schema:
        return {
            "version": 1,
            "project_id": project_id,
            "summary": "",
            "required_captcha_types": [],
            "allowed_captcha_ids": [],
            "allowed_email_ids": [],
            "allowed_sms_ids": [],
            "task_ui": {"show_headless": False},
            "allowed_proxy_ids": [],
            "defaults": {},
            "fields": [],
            "steps": [],
            "output": {"title": "产出", "preview_limit": 50},
            "notes": [],
            "help_md": "",
            "schema_path": str(schema_path),
            "has_schema": False,
        }

    help_name = schema.get("help_file") or "help.md"
    help_md = _read_text(base / str(help_name))
    schema = dict(schema)
    schema.setdefault("project_id", project_id)
    schema["help_md"] = help_md
    schema["schema_path"] = str(schema_path)
    schema["has_schema"] = True
    schema.setdefault("fields", [])
    schema.setdefault("steps", [])
    schema.setdefault("notes", [])
    schema.setdefault("defaults", {})
    schema.setdefault("allowed_email_ids", [])
    schema.setdefault("allowed_sms_ids", [])
    schema.setdefault("allowed_proxy_ids", [])
    schema.setdefault("required_captcha_types", [])
    schema.setdefault("allowed_captcha_ids", [])
    schema.setdefault("task_ui", {"show_headless": False})
    schema.setdefault("output", {"title": "产出", "preview_limit": 50})
    return schema


def list_project_ui_meta() -> list[dict[str, Any]]:
    projects_dir = ROOT / "projects"
    if not projects_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for child in sorted(projects_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if not (child / "project.py").exists():
            continue
        ui = load_project_ui(child.name)
        items.append(
            {
                "id": child.name,
                "has_schema": bool(ui.get("has_schema")),
                "steps_count": len(ui.get("steps") or []),
                "fields_count": len(ui.get("fields") or []),
            }
        )
    return items
