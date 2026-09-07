"""chatgpt2api 注册服务 — RegiForge 任务桥接模式（v4：自动补号 + 定时巡检）。

保持与原 register_service.py 相同的公共方法契约（get/update/start/stop/reset/
reset_outlook_pool/gptmail_status/refresh_gptmail_public_key），前端 /#/register
无需任何改动。

任务模式语义：
- mode=quota   → 按目标额度注册（RegiForge total=target_quota）
- mode=available → 按可用额度注册（RegiForge total=target_available）
- mode=total   → 按账号池目标数注册：注册总数输入=目标池数量，
                 自动注册「目标 - 当前账号池数量」差额，任务完成后池仍不足则
                 自动续跑补号，直到达到目标或用户点击停止。

自动注册（auto_refill）：
- auto_refill=true 时，后台守护线程每 auto_refill_interval 秒（默认 300，
  即每 5 分钟）巡检一次 chatgpt2api 账号池；池数量低于注册总数（目标池）
  且当前无任务运行、mode=total 时，自动创建 RegiForge 任务补齐差额，
  直到账号池达到目标数量为止。false 则完全关闭巡检。
- 手动「启动」不受影响；手动「停止」只停当前任务，auto_refill 设置保留。

注册任务由 RegiForge 的 chatgpt_register 项目执行：
  POST {REGIFORGE_BASE}/api/tasks  创建任务（chatgpt_register + mailnest + wary）
  轮询 {REGIFORGE_BASE}/api/tasks/{task_id} 更新 stats/logs
  任务完成后由 RegiForge 自动导入 chatgpt2api 账号池（import.auto=true）

不再 import services/register.openai_register / mail_provider（自带注册执行器已弃用）。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from services.config import DATA_DIR
from services.json_file import read_json_object, write_json_file
from services.account_service import account_service


REGISTER_FILE = DATA_DIR / "register.json"

# RegiForge 任务参数（默认对齐 chatgpt_register 主路径）
REGIFORGE_BASE = os.environ.get("REGIFORGE_BASE_URL", "http://regiforge:8787").rstrip("/")
REGIFORGE_PROJECT = os.environ.get("REGIFORGE_PROJECT_ID", "chatgpt_register")
REGIFORGE_EMAIL = os.environ.get("REGIFORGE_EMAIL_ID", "mailnest")
REGIFORGE_PROXY = os.environ.get("REGIFORGE_PROXY_ID", "wary")
REGIFORGE_CAPTCHA = os.environ.get("REGIFORGE_CAPTCHA_ID", "turnstile.browser_manual")
REGIFORGE_SMS = os.environ.get("REGIFORGE_SMS_ID", "")


def _safe_bool(value: object, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _runtime_channel() -> dict:
    """当前 RegiForge 实际执行通道（邮箱/代理/验证码），供前端如实展示。"""
    return {
        "email_id": REGIFORGE_EMAIL,
        "proxy_id": REGIFORGE_PROXY,
        "captcha_id": REGIFORGE_CAPTCHA,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# 前端 /#/register 的「启动」按钮要求至少一个已启用邮箱来源且无缺失必填项
# （bl/fl/gl + _e 校验）。注册邮箱实际由 RegiForge mailest 通道执行，此占位
# provider 不参与收码，仅用于满足前端启动条件。gptmail 默认 key_mode=public
# 时 _e 校验无必填项，是最省事的占位类型。
PLACEHOLDER_MAIL_PROVIDER = {
    "id": "regiforge-mailnest",
    "enable": True,
    "type": "gptmail",
    "key_mode": "public",
    "api_key": "",
    "default_domain": "",
    "local_compose": False,
}


def _fixed_mail_providers() -> list[dict]:
    """chatgpt2api 侧邮箱来源已由 RegiForge mailest 通道取代：收码/发码不再走
    chatgpt2api provider。固定只返回一个 gptmail 占位来源，保证前端 /#/register
    的「启动」按钮始终可用（gptmail key_mode=public 时前端 _e 校验零必填项）。
    """
    return [PLACEHOLDER_MAIL_PROVIDER]


def _default_config() -> dict:
    return {
        "mail": {"providers": [PLACEHOLDER_MAIL_PROVIDER], "api_use_register_proxy": True},
        "proxy": "",
        "total": 500,
        "threads": 2,
        "mode": "total",
        "target_quota": 100,
        "target_available": 10,
        "check_interval": 5,
        "auto_refill": False,
        "auto_refill_interval": 300,
        "enabled": False,
        "channel": _runtime_channel(),
        "stats": {
            "success": 0, "fail": 0, "done": 0, "running": 0, "threads": 2,
            "elapsed_seconds": 0, "avg_seconds": 0, "success_rate": 0,
            "current_quota": 0, "current_available": 0,
        },
    }


def _normalize(raw: dict) -> dict:
    cfg = _default_config()
    cfg.update({k: v for k, v in raw.items() if k not in {"stats", "logs"}})
    cfg["total"] = max(1, int(cfg.get("total") or 1))
    cfg["threads"] = max(1, int(cfg.get("threads") or 1))
    cfg["mode"] = (
        str(cfg.get("mode") or "total").strip()
        if str(cfg.get("mode") or "total").strip() in {"total", "quota", "available"} else "total"
    )
    cfg["target_quota"] = max(1, int(cfg.get("target_quota") or 1))
    cfg["target_available"] = max(1, int(cfg.get("target_available") or 1))
    cfg["check_interval"] = max(1, int(cfg.get("check_interval") or 5))
    cfg["auto_refill"] = _safe_bool(cfg.get("auto_refill"), False)
    cfg["auto_refill_interval"] = max(30, min(3600, int(cfg.get("auto_refill_interval") or 300)))
    cfg["proxy"] = str(cfg.get("proxy") or "").strip()
    mail = cfg.get("mail") if isinstance(cfg.get("mail"), dict) else {}
    cfg["mail"] = {**_default_config()["mail"], **mail}
    cfg["mail"]["providers"] = _fixed_mail_providers()
    cfg["mail"]["api_use_register_proxy"] = _safe_bool(cfg["mail"].get("api_use_register_proxy"), True)
    cfg["mail"].pop("proxy", None)
    cfg["enabled"] = bool(cfg.get("enabled"))
    cfg["channel"] = _runtime_channel()
    stats = {**_default_config()["stats"], **(raw.get("stats") if isinstance(raw.get("stats"), dict) else {}),
             "threads": cfg["threads"]}
    cfg["stats"] = stats
    return cfg


# 全部 HTTP 请求走旁路代理的 opener：容器内互访（regiforge / 127.0.0.1）绝不能被
# HTTP(S)_PROXY 环境变量劫持转发到外网代理。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: int = 30) -> dict | None:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


class RegisterService:
    """bridge：chatgpt2api 前端 register 页面 → RegiForge 任务（含自动补号）"""

    def __init__(self, store_file: Path):
        self._store_file = store_file
        self._lock = threading.RLock()
        self._poll_thread: threading.Thread | None = None
        self._starting = False  # 串行化 create-task，避免手动启动/自动续跑/定时巡检并发起任务
        self._logs: list[dict] = []
        self._config = self._load()
        if self._config.get("enabled") and self._config["stats"].get("task_id"):
            self._spawn_poll(str(self._config["stats"]["task_id"]))
        self._refill_thread = threading.Thread(
            target=self._refill_loop, daemon=True, name="regiforge-refill"
        )
        self._refill_thread.start()

    def _load(self) -> dict:
        return _normalize(read_json_object(self._store_file, name="register.json"))

    def _save(self) -> None:
        write_json_file(self._store_file, self._config)

    # ---------- 前端契约 ----------

    def get(self) -> dict:
        with self._lock:
            return json.loads(json.dumps({**self._config, "logs": self._logs[-300:]}, ensure_ascii=False))

    def update(self, updates: dict) -> dict:
        with self._lock:
            allowed = {
                "total", "threads", "mode", "target_quota", "target_available",
                "check_interval", "auto_refill", "auto_refill_interval",
                "channel",
                "proxy", "mail", "enabled",
            }
            merged = {**self._config, **{k: v for k, v in updates.items() if k in allowed}}
            self._config = _normalize(merged)
            self._save()
        return self.get()

    def start(self) -> dict:
        with self._lock:
            if self._poll_thread and self._poll_thread.is_alive():
                self._append_log("已有 RegiForge 任务在运行，忽略重复启动", "yellow")
                self._config["enabled"] = True
                self._save()
                return self.get()
            cfg = self._config
            mode = str(cfg.get("mode") or "total")
            total = max(1, int(cfg.get("total") or 1))
            threads = max(1, int(cfg.get("threads") or 1))
            target = total
            plan = total
            if mode == "quota":
                plan = int(cfg.get("target_quota") or total)
                target = plan
            elif mode == "available":
                plan = int(cfg.get("target_available") or total)
                target = plan
            else:
                # mode=total：注册总数=目标池数量，自动注册差额
                try:
                    pool_total = self._fetch_pool_total()
                except Exception as exc:
                    self._append_log(f"查询账号池数量失败：{exc}，按 total={total} 直接注册", "yellow")
                    pool_total = 0
                plan = max(0, total - pool_total)
                if plan == 0:
                    self._config["enabled"] = False
                    self._save()
                    self._append_log(f"账号池已达目标：总数 {pool_total} >= {total}，无需注册", "green")
                    return self.get()
                self._append_log(
                    f"账号池当前 {pool_total}，目标 {total}，计划注册 {plan} 个"
                    + (f"（线程 {threads}）" if threads > 1 else ""), "yellow"
                )
            self._start_task(plan, threads, mode=mode, target=target)
        return self.get()

    def stop(self) -> dict:
        with self._lock:
            task_id = str(self._config["stats"].get("task_id") or "")
            self._config["enabled"] = False
            self._config["auto_follow"] = False
            self._save()
            self._append_log("正在停止 RegiForge 任务", "yellow")
        if task_id:
            try:
                _http_json(f"{REGIFORGE_BASE}/api/tasks/{task_id}/stop", "POST", timeout=20)
            except Exception as exc:
                self._append_log(f"停止请求失败：{exc}", "red")
        return self.get()

    def reset(self) -> dict:
        with self._lock:
            task_id = str(self._config["stats"].get("task_id") or "") if self._config.get("enabled") else ""
            self._logs = []
            self._config["enabled"] = False
            self._config["auto_follow"] = False
            self._config["stats"] = {
                "success": 0, "fail": 0, "done": 0, "running": 0, "threads": self._config["threads"],
                "elapsed_seconds": 0, "avg_seconds": 0, "success_rate": 0,
                "current_quota": 0, "current_available": 0, "updated_at": _now(),
            }
            self._save()
        # 若正在运行则先停掉底层 RegiForge 任务，避免 reset 清掉 task_id 后 stop 失效
        if task_id:
            try:
                _http_json(f"{REGIFORGE_BASE}/api/tasks/{task_id}/stop", "POST", timeout=20)
                self._append_log(f"reset 前已停止任务 {task_id}", "yellow")
            except Exception as exc:
                self._append_log(f"reset 停止任务失败：{exc}", "red")
        return self.get()

    def reset_outlook_pool(self, scope: str = "all") -> dict:
        self._append_log("Outlook 邮箱池已由 RegiForge 邮箱通道取代，无需维护", "yellow")
        return self.get()

    def gptmail_status(self, provider: dict | None = None, force: bool = False) -> dict:
        return {"status": "disabled", "message": "gptmail 已由 RegiForge 任务模式取代"}

    def refresh_gptmail_public_key(self, provider: dict | None = None, force: bool = True) -> dict:
        return {"status": "disabled", "message": "gptmail 已由 RegiForge 任务模式取代"}

    # ---------- RegiForge 任务 ----------

    def _start_task(self, plan: int, threads: int, mode: str = "total", target: int = 0) -> None:
        # 串行化任务创建：轮询线程的自动续跑 / 定时巡检 / 手动 start 可能同时触发
        with self._lock:
            if self._starting:
                return
            self._starting = True
        try:
            self._start_task_locked(plan, threads, mode=mode, target=target)
        finally:
            with self._lock:
                self._starting = False

    def _start_task_locked(self, plan: int, threads: int, mode: str = "total", target: int = 0) -> None:
        payload = {
            "project_id": REGIFORGE_PROJECT,
            "captcha_id": REGIFORGE_CAPTCHA,
            "email_id": REGIFORGE_EMAIL,
            "proxy_id": REGIFORGE_PROXY,
            "sms_id": REGIFORGE_SMS,
            "total": plan,
            "start": 1,
            "concurrency": threads,
            "stagger": 0,
            "headless": False,
        }
        try:
            resp = _http_json(f"{REGIFORGE_BASE}/api/tasks", "POST", payload, timeout=60)
        except Exception as exc:
            self._append_log(f"创建 RegiForge 任务失败：{exc}", "red")
            return
        task_id = str(resp.get("task_id") or "") if resp else ""
        if not task_id:
            self._append_log("RegiForge 未返回 task_id，任务未创建", "red")
            return
        self._config["enabled"] = True
        self._config["auto_follow"] = True if mode == "total" else False
        self._config["stats"] = {
            "job_id": task_id, "task_id": task_id, "success": 0, "fail": 0, "done": 0,
            "running": 0, "threads": threads, "elapsed_seconds": 0, "avg_seconds": 0,
            "success_rate": 0, "current_quota": 0, "current_available": 0,
            "target_pool": target,
            "started_at": _now(), "updated_at": _now(),
        }
        self._logs.append({"time": _now(), "text": "———— 新任务开始 ————", "level": "info"})
        self._logs = self._logs[-300:]
        self._save()
        self._append_log(
            f"RegiForge 任务已创建 task_id={task_id}：total={plan} threads={threads} mode={mode} "
            f"project={REGIFORGE_PROJECT} email={REGIFORGE_EMAIL} proxy={REGIFORGE_PROXY}", "green"
        )
        self._spawn_poll(task_id)

    def _spawn_poll(self, task_id: str) -> None:
        self._poll_thread = threading.Thread(target=self._poll, args=(task_id,), daemon=True, name="regiforge-poll")
        self._poll_thread.start()

    def _poll(self, task_id: str) -> None:
        try:
            while True:
                resp = _http_json(f"{REGIFORGE_BASE}/api/tasks/{task_id}", "GET", timeout=20) or {}
                done = int(resp.get("done") or 0)
                ok = int(resp.get("ok") or 0)
                failed = int(resp.get("failed") or 0)
                state = str(resp.get("state") or "")
                success_rate = round(ok * 100 / max(1, ok + failed), 1) if (ok + failed) else 0
                finished = state in {"done", "failed", "stopped", "cancelled"}
                running = 0 if finished else int(resp.get("total") or 0) - done
                self._bump(done=done, success=ok, fail=failed, running=max(0, running), success_rate=success_rate)
                if finished:
                    self._bump(running=0, finished_at=_now())
                    self._append_log(
                        f"RegiForge 任务结束：state={state} ok={ok} failed={failed}",
                        "green" if state == "done" and failed == 0 else "yellow",
                    )
                    self._set_enabled(False)
                    if state == "stopped":
                        self._append_log("任务已停止", "yellow")
                        break
                    self._maybe_continue()
                    break
                try:
                    logs = _http_json(f"{REGIFORGE_BASE}/api/tasks/{task_id}/logs", "GET", timeout=20) or {}
                    for line in (logs.get("lines") or [])[-15:]:
                        with self._lock:
                            if not any(existing.get("text") == str(line) for existing in self._logs[-60:]):
                                self._append_log(str(line), "info")
                except Exception:
                    pass
                time.sleep(max(1, int(self._config.get("check_interval") or 5)))
        except Exception as exc:
            self._set_enabled(False)
            self._append_log(f"轮询 RegiForge 异常：{exc}", "red")

    def _maybe_continue(self) -> None:
        """mode=total 自动补号：任务结束后账号池仍不足目标，则自动启动下一轮。"""
        try:
            with self._lock:
                follow = self._config.get("auto_follow")
                mode = str(self._config.get("mode") or "total")
                target = int(self._config["stats"].get("target_pool") or int(self._config.get("total") or 0))
                threads = max(1, int(self._config.get("threads") or 1))
            if not follow or mode != "total" or target <= 0:
                return
            pool_total = self._fetch_pool_total()
            if pool_total >= target:
                self._append_log(f"账号池已达目标 {pool_total} >= {target}，自动注册完成", "green")
                return
            plan = target - pool_total
            self._append_log(f"账号池 {pool_total} < 目标 {target}，自动补号 {plan} 个", "yellow")
            with self._lock:
                self._start_task(plan, threads, mode="total", target=target)
        except Exception as exc:
            self._append_log(f"自动补号异常：{exc}", "red")

    # ---------- 自动注册（定时巡检补齐） ----------

    def _refill_loop(self) -> None:
        """后台守护线程：每 auto_refill_interval 秒巡检一次账号池，开启
        auto_refill 且池少于目标时自动补齐。线程常驻，开关只影响动作。
        """
        while True:
            try:
                interval = int(self._config.get("auto_refill_interval") or 300)
                time.sleep(max(1, min(interval, 300)))
                self._refill_check()
            except Exception as exc:
                self._append_log(f"自动注册巡检异常：{exc}", "red")
                time.sleep(30)

    def _refill_check(self) -> None:
        """一次巡检：auto_refill 开 + 无运行任务 + mode=total + 池 < 目标 → 补齐差额。"""
        with self._lock:
            if not self._config.get("auto_refill"):
                return
            if self._config.get("enabled"):
                return  # 任务运行中，交由任务自身的续跑逻辑处理
            if self._poll_thread and self._poll_thread.is_alive():
                return
            mode = str(self._config.get("mode") or "total")
            total = max(1, int(self._config.get("total") or 1))
            threads = max(1, int(self._config.get("threads") or 1))
            if mode != "total":
                return  # 定时补齐只按「注册总数」目标池语义生效
            try:
                pool_total = self._fetch_pool_total()
            except Exception as exc:
                self._append_log(f"自动注册查询账号池失败：{exc}", "red")
                return
            plan = max(0, total - pool_total)
            if plan == 0:
                return  # 达标，静默等待下一轮
        self._append_log(
            f"自动注册巡检：账号池当前 {pool_total} < 目标 {total}，自动补齐 {plan} 个"
            + (f"（线程 {threads}）" if threads > 1 else ""), "yellow"
        )
        self._start_task(plan, threads, mode="total", target=total)

    def _fetch_pool_total(self) -> int:
        """查询 chatgpt2api 账号池当前数量。

        直接读本进程存储层（account_service.get_stats），与 /api/accounts 的 total
        同源，但零 HTTP、零自环；不会出现「桥 → regiforge → 回环调 chatgpt2api」
        这类跨进程回环不稳定。失败时抛异常由调用方按 total 兜底处理。
        """
        stats = account_service.get_stats() or {}
        return max(0, int(stats.get("total") or 0))

    def _set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._config["enabled"] = enabled
            self._save()

    def _bump(self, **updates) -> None:
        with self._lock:
            self._config["stats"].update(updates)
            stats = self._config["stats"]
            started_at = str(stats.get("started_at") or "")
            if started_at:
                try:
                    elapsed = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(started_at)).total_seconds())
                    stats["elapsed_seconds"] = round(elapsed, 1)
                except Exception:
                    pass
            success = int(stats.get("success") or 0)
            fail = int(stats.get("fail") or 0)
            stats["avg_seconds"] = round(float(stats.get("elapsed_seconds") or 0) / success, 1) if success else 0
            stats["success_rate"] = round(success * 100 / max(1, success + fail), 1)
            stats["updated_at"] = _now()
            self._save()

    def _append_log(self, text: str, color: str = "") -> None:
        with self._lock:
            self._logs.append({"time": _now(), "text": str(text), "level": str(color or "info")})
            self._logs = self._logs[-300:]


register_service = RegisterService(REGISTER_FILE)