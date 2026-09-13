from __future__ import annotations

import sys

# Windows: Playwright/patchright 依赖 asyncio.create_subprocess_exec，
# 而 uvicorn 默认 SelectorEventLoop 不支持子进程；强制 ProactorEventLoop。
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.config_store import load_config, save_config
from core.models import AccountResult, TaskConfig
from core.paths import project_accounts_file, project_keys_file
from core.project_ui import load_project_ui, load_provider_ui_schema
from core.registry import get_registry
from core.task_runner import get_runner

app = FastAPI(title="RegiForge", description="共用注册平台控制台")
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class TaskCreateBody(BaseModel):
    project_id: str
    captcha_id: str
    email_id: str
    proxy_id: str = "socks5"
    sms_id: str = ""
    total: int = Field(default=1, ge=1)
    start: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1)
    stagger: int = Field(default=0, ge=0)
    headless: bool = False


class ConfigBody(BaseModel):
    config: dict


class AccountBody(BaseModel):
    email: str = ""
    credential: str


class VerificationRequestBody(BaseModel):
    verifier_id: str
    account: AccountBody


class ExportRequestBody(BaseModel):
    exporter_id: str
    project_id: str
    accounts: list[AccountBody]


class ConsumeKeysBody(BaseModel):
    credentials: list[str]


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")


@app.get("/projects/{project_id}")
async def project_page(project_id: str):
    registry = get_registry()
    registry.load()
    if project_id not in registry.projects:
        raise HTTPException(status_code=404, detail=f"未知项目: {project_id}")
    return FileResponse(static_dir / "index.html")


@app.get("/api/meta")
async def api_meta():
    return get_registry().meta()


@app.get("/api/projects/{project_id}/ui")
async def api_project_ui(project_id: str):
    """读取项目 UI 规划（projects/<id>/ui/schema.json）。"""
    reg = get_registry()
    reg.load()
    if project_id not in reg.projects:
        raise HTTPException(status_code=404, detail=f"未知项目: {project_id}")
    return load_project_ui(project_id)


@app.get("/api/ui/providers")
async def api_provider_ui():
    return load_provider_ui_schema()


@app.get("/api/config")
async def api_get_config():
    return load_config()


@app.put("/api/config")
async def api_put_config(body: ConfigBody):
    return save_config(body.config)


@app.post("/api/verify")
async def api_verify_account(body: VerificationRequestBody):
    config = load_config()
    verifier = get_registry().get_verifier(body.verifier_id)
    verifier.configure((config.get("verify") or {}).get(body.verifier_id) or {})
    account = AccountResult(email=body.account.email, apikey=body.account.credential)
    return (await verifier.verify(account)).to_dict()


@app.post("/api/export")
async def api_export_accounts(body: ExportRequestBody):
    config = load_config()
    exporter = get_registry().get_exporter(body.exporter_id)
    exporter_config = dict((config.get("export") or {}).get(body.exporter_id) or {})
    exporter_config["project_id"] = body.project_id
    exporter.configure(exporter_config)
    accounts = [AccountResult(email=item.email, apikey=item.credential) for item in body.accounts]
    result = await exporter.export(accounts)
    payload = result.to_dict()
    payload["project_id"] = body.project_id
    return payload


@app.delete("/api/keys/{project_id}")
async def api_clear_keys(project_id: str):
    registry = get_registry()
    registry.load()
    if project_id not in registry.projects:
        raise HTTPException(status_code=404, detail=f"未知项目: {project_id}")
    output_dir = load_config().get("ui", {}).get("keys_output_dir", "")
    keys_path = project_keys_file(project_id, output_dir)
    accounts_path = project_accounts_file(project_id, output_dir)
    removed = len(keys_path.read_text(encoding="utf-8").splitlines()) if keys_path.exists() else 0
    keys_path.write_text("", encoding="utf-8")
    accounts_path.write_text("", encoding="utf-8")
    return {"project_id": project_id, "removed": removed, "remaining": 0}


@app.post("/api/keys/{project_id}/consume")
async def api_consume_keys(project_id: str, body: ConsumeKeysBody):
    config = load_config()
    path = project_keys_file(project_id, config.get("ui", {}).get("keys_output_dir", ""))
    if not path.exists():
        return {"removed": 0, "remaining": 0}
    remove = {credential.strip() for credential in body.credentials if credential.strip()}
    lines = path.read_text(encoding="utf-8").splitlines()
    kept: list[str] = []
    removed = 0
    for line in lines:
        credential = line.split("|", 1)[1].strip() if "|" in line else line.strip()
        if credential in remove:
            removed += 1
        else:
            kept.append(line)
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")

    accounts_path = project_accounts_file(project_id, config.get("ui", {}).get("keys_output_dir", ""))
    if accounts_path.exists():
        import json as _json
        structured_kept: list[str] = []
        for line in accounts_path.read_text(encoding="utf-8").splitlines():
            try:
                account = _json.loads(line)
            except Exception:
                structured_kept.append(line)
                continue
            if str(account.get("apikey") or "").strip() not in remove:
                structured_kept.append(line)
        accounts_path.write_text(
            "\n".join(structured_kept) + ("\n" if structured_kept else ""),
            encoding="utf-8",
        )

    return {"removed": removed, "remaining": len(kept)}


@app.get("/api/tasks")
async def api_list_tasks():
    return get_runner().list_tasks()


@app.post("/api/tasks")
async def api_create_task(body: TaskCreateBody):
    cfg = TaskConfig(
        project_id=body.project_id,
        captcha_id=body.captcha_id,
        email_id=body.email_id,
        proxy_id=body.proxy_id,
        sms_id=body.sms_id,
        total=body.total,
        start=body.start,
        concurrency=body.concurrency,
        stagger=body.stagger,
        headless=body.headless,
    )
    conf = load_config()
    conf.setdefault("ui", {})
    conf["ui"].update(
        {
            "last_project_id": body.project_id,
            "last_captcha_id": body.captcha_id,
            "last_email_id": body.email_id,
            "last_proxy_id": body.proxy_id,
            "last_sms_id": body.sms_id,
            "last_total": body.total,
            "last_start": body.start,
            "last_concurrency": body.concurrency,
            "last_stagger": body.stagger,
            "last_headless": body.headless,
        }
    )
    save_config(conf)

    try:
        status = await get_runner().start(cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return status.to_dict()


@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str):
    status = get_runner().get_task(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="任务不存在")
    return status.to_dict()


@app.post("/api/tasks/{task_id}/stop")
async def api_stop_task(task_id: str):
    try:
        status = await get_runner().stop(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return status.to_dict()


@app.get("/api/tasks/{task_id}/logs")
async def api_task_logs(task_id: str, offset: int = 0):
    if not get_runner().get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return get_runner().get_logs(task_id, offset=offset)


@app.get("/api/keys")
async def api_all_keys(limit: int = 100):
    config = load_config()
    output_dir = config.get("ui", {}).get("keys_output_dir", "")
    registry = get_registry()
    registry.load()
    accounts = []
    for project_id in registry.projects:
        path = project_keys_file(project_id, output_dir)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                accounts.append({"project_id": project_id, "line": line})
    return {"count": len(accounts), "accounts": accounts[-limit:]}


@app.get("/api/keys/{project_id}")
async def api_keys(project_id: str, limit: int = 50):
    output_dir = load_config().get("ui", {}).get("keys_output_dir", "")
    keys_path = project_keys_file(project_id, output_dir)
    accounts_path = project_accounts_file(project_id, output_dir)

    # 优先读结构化 JSONL
    structured: list[dict] = []
    if accounts_path.exists():
        import json as _json
        for line in accounts_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                structured.append(_json.loads(line))
            except Exception:
                pass

    if not keys_path.exists():
        return {"file": str(keys_path), "lines": [], "count": 0, "accounts": [], "today_count": 0}

    lines = keys_path.read_text(encoding="utf-8").splitlines()

    # 无 JSONL 时从 txt 回退解析
    if not structured:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 1)
            structured.append({
                "email": parts[0] if parts else "",
                "apikey": parts[1] if len(parts) > 1 else "",
                "registered_at": None,
                "extra": {},
            })

    # 统计今日新增（全量，不受 limit 限制）
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    today_count = 0
    for acc in structured:
        ts = acc.get("registered_at")
        if not ts:
            continue
        try:
            # 兼容带/不带时区的 ISO 时间戳
            d = datetime.fromisoformat(ts)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            # 按本地日期判断"今日"（与前端 isToday 一致）
            local_d = d.astimezone()
            local_now = now.astimezone()
            if (local_d.year == local_now.year
                    and local_d.month == local_now.month
                    and local_d.day == local_now.day):
                today_count += 1
        except Exception:
            continue

    return {
        "file": str(keys_path),
        "count": len(lines),
        "lines": lines[-limit:],
        "accounts": structured[-limit:],
        "today_count": today_count,
    }
