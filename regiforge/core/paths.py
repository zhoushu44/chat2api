from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
CONFIG_EXAMPLE = ROOT / "config" / "settings.example.json"
KEYS_DIR = DATA_DIR / "keys"
TASKS_DIR = DATA_DIR / "tasks"
LOGS_DIR = DATA_DIR / "logs"
DEBUG_DIR = DATA_DIR / "debug"


def ensure_data_dirs() -> None:
    for path in (DATA_DIR, KEYS_DIR, TASKS_DIR, LOGS_DIR, DEBUG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def account_debug_dir(project_id: str, task_id: str, index: int) -> Path:
    """失败证据目录：data/debug/<project>/<task>/<index>/"""
    ensure_data_dirs()
    folder = DEBUG_DIR / project_id / (task_id or "notask") / f"{int(index):04d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def project_keys_file(project_id: str, output_dir: str = "") -> Path:
    output_dir = str(output_dir or "").strip()
    if output_dir:
        folder = Path(output_dir).expanduser()
        if not folder.is_absolute():
            folder = ROOT / folder
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{project_id}_api_keys.txt"

    ensure_data_dirs()
    folder = KEYS_DIR / project_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "api_keys.txt"


def project_accounts_file(project_id: str, output_dir: str = "") -> Path:
    """结构化账号文件（JSONL），与 api_keys.txt 同目录，文件名 accounts.jsonl。"""
    output_dir = str(output_dir or "").strip()
    if output_dir:
        folder = Path(output_dir).expanduser()
        if not folder.is_absolute():
            folder = ROOT / folder
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{project_id}_accounts.jsonl"

    ensure_data_dirs()
    folder = KEYS_DIR / project_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "accounts.jsonl"
