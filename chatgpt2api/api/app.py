from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from threading import Event

from anyio.to_thread import current_default_thread_limiter
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api import accounts, ai, image_tasks, prompts, register, system
from api.errors import install_exception_handlers
from api.support import resolve_web_asset, start_limited_account_watcher
from services.account_service import account_service
from services.backup_service import backup_service
from services.config import DATA_DIR, config
from services.dashboard_metrics_service import dashboard_metrics_service
from services.image_service import start_image_cleanup_scheduler
from services.log_service import cleanup_old_logs, start_log_cleanup_scheduler
from services.realtime_monitor_service import realtime_monitor_service
from utils.log import logger


def _env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(str(os.getenv(name, "") or default).strip())
    except (TypeError, ValueError):
        value = default
    value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _configure_threadpool() -> None:
    tokens = _env_int("CHATGPT2API_THREAD_TOKENS", 80, 1)
    limiter = current_default_thread_limiter()
    previous = int(getattr(limiter, "total_tokens", 0) or 0)
    if previous != tokens:
        limiter.total_tokens = tokens
    realtime_monitor_service.set_threadpool(tokens=tokens, previous_tokens=previous)
    logger.info({
        "event": "runtime_threadpool_configured",
        "previous_tokens": previous,
        "tokens": tokens,
    })


def _parse_local_ts(value: object):
    """兼容 'YYYY-MM-DD HH:MM:SS' 与 ISO 的时间解析，返回本地时间戳或 None。"""
    if value is None or value == "":
        return None
    text = str(value).strip()[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except (ValueError, OSError, OverflowError):
            continue
    return None


def _dashboard_metrics() -> dict:
    """概览运营指标：平均生图、24h 死号率、注册成功率、单邮箱成本、单张图成本。"""
    items = account_service.list_accounts()
    total = len(items)
    logger.info({"event": "dashboard_metrics_start", "account_count": total})
    total_success = sum(int(a.get("success") or 0) for a in items)
    avg_images = round(total_success / total, 2) if total else 0.0
    logger.info({
        "event": "dashboard_metrics_avg",
        "total_success": total_success,
        "account_count": total,
        "avg_images_per_account": avg_images,
    })

    now_ts = time.time()
    window = now_ts - 24 * 3600
    dead_total = 0
    dead_24h = 0
    for a in items:
        if a.get("status") not in ("异常", "禁用"):
            continue
        dead_total += 1
        ts = _parse_local_ts(a.get("last_invalid_at"))
        if ts is not None and ts >= window:
            dead_24h += 1
    death_rate_24h = round(dead_24h / total * 100, 2) if total else 0.0
    logger.info({
        "event": "dashboard_metrics_dead",
        "window_seconds": 86400,
        "dead_total": dead_total,
        "dead_24h": dead_24h,
        "death_rate_24h": death_rate_24h,
        "denominator": total,
    })

    register_success_rate = 0.0
    try:
        _stats = json.loads((DATA_DIR / "register.json").read_text(encoding="utf-8")).get("stats") or {}
        register_success_rate = float(_stats.get("success_rate") or 0.0)
        logger.info({
            "event": "dashboard_metrics_register",
            "register_stats": _stats,
            "success_rate": register_success_rate,
        })
    except Exception as exc:
        logger.error({
            "event": "dashboard_metrics_register_failed",
            "error": str(exc),
            "path": str(DATA_DIR / "register.json"),
        })

    email_cost = 0.018
    cost_per_image = None
    if register_success_rate > 0 and avg_images > 0:
        cost_per_image = round(email_cost / (register_success_rate / 100.0 * avg_images), 4)
    logger.info({
        "event": "dashboard_metrics_cost",
        "email_cost": email_cost,
        "register_success_rate": register_success_rate,
        "avg_images_per_account": avg_images,
        "cost_per_image": cost_per_image,
    })

    result = {
        "total_accounts": total,
        "total_success": total_success,
        "avg_images_per_account": avg_images,
        "dead_total": dead_total,
        "dead_24h": dead_24h,
        "death_rate_24h": death_rate_24h,
        "register_success_rate": register_success_rate,
        "email_cost": email_cost,
        "cost_per_image": cost_per_image,
    }
    logger.info({"event": "dashboard_metrics_done", "metrics": result})
    return result


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _configure_threadpool()
        account_service.cleanup_auto_remove_accounts()
        stop_event = Event()
        thread = start_limited_account_watcher(stop_event)
        cleanup_thread = start_image_cleanup_scheduler(stop_event)
        log_cleanup_thread = start_log_cleanup_scheduler(stop_event)
        backup_service.start()
        config.cleanup_old_images()
        cleanup_old_logs()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)
            cleanup_thread.join(timeout=1)
            log_cleanup_thread.join(timeout=1)
            try:
                dashboard_metrics_service.flush()
            except Exception as exc:
                logger.error({"event": "dashboard_metrics_shutdown_flush_failed", "error": str(exc)})
            backup_service.stop()

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(ai.create_router())
    app.include_router(accounts.create_router())
    app.include_router(image_tasks.create_router())
    app.include_router(prompts.create_router())
    app.include_router(register.create_router())
    app.include_router(system.create_router(app_version))

    # 概览运营指标：为 /api/dashboard 响应注入 metrics（不动原 system.py）
    @app.middleware("http")
    async def _inject_dashboard_metrics(request, call_next):
        response = await call_next(request)
        if request.url.path != "/api/dashboard" or response.status_code != 200:
            return response
        _inject_start = time.perf_counter()
        try:
            chunks = [chunk async for chunk in response.body_iterator]
            payload = json.loads(b"".join(chunks).decode("utf-8"))
            if isinstance(payload, dict):
                metrics = payload.get("metrics")
                if not isinstance(metrics, dict):
                    metrics = {}
                    payload["metrics"] = metrics
                metrics.update(_dashboard_metrics())
                headers = {
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() not in ("content-length", "transfer-encoding")
                }
                elapsed_ms = round((time.perf_counter() - _inject_start) * 1000, 1)
                logger.info({
                    "event": "dashboard_metrics_injected",
                    "elapsed_ms": elapsed_ms,
                    "payload_keys": sorted(payload.keys()),
                })
                return JSONResponse(
                    content=payload, status_code=response.status_code, headers=headers
                )
        except Exception as exc:
            logger.error({
                "event": "dashboard_metrics_injection_failed",
                "error": str(exc),
                "elapsed_ms": round((time.perf_counter() - _inject_start) * 1000, 1),
            })
        return response

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(asset, headers={"Cache-Control": "no-cache"})

    return app