"""abai 方案移植：纯 HTTP + 常驻 Node V8 沙箱计算 Sentinel 首提 token，全程不开浏览器。

流程：
1. Python 本地算 requirements PoW（FNV1a-32 | 25 字段指纹 | gAAAAAC 前缀）
2. POST sentinel.openai.com/backend-api/sentinel/req 拿 challenge
3. turnstile.dx / so.dx 存在时，交给常驻 Node `node:vm` 沙箱跑官方 sdk.js 出 token
4. 组 openai-sentinel-token / openai-sentinel-so-token 头（紧凑 JSON 字符串）

替代原 `extract_sentinel`（Playwright 开 Chrome）路径：
- 无 Chrome 内存开销（原来每号 ~285MB）
- sdk.js 自动发现、缓存与更新（SentinelSDKManager）
- V8 worker 按时区懒启动（每 worker 固定 TZ，与指纹时区一致）

模式由 CHATGPT_SENTINEL_MODE 控制：v8（纯 V8）/ browser（原浏览器）/
auto（默认：先 v8，失败回退 browser）。
首 token 的 flow 由 CHATGPT_SENTINEL_FIRST_FLOW 控制（默认 main，与原浏览器一致）。
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import queue
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
import zoneinfo
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

SENTINEL_BASE = "https://sentinel.openai.com"
SENTINEL_REQ_URL = f"{SENTINEL_BASE}/backend-api/sentinel/req"

LogFn = Callable[[str], None]

_SDK_VERSION_RE = re.compile(
    r"[\"']([^\"']*/sentinel/([A-Za-z0-9._-]+)/sdk\.js)[\"']", re.IGNORECASE
)

_SDK_DIR = Path(__file__).with_name("sentinel_vm")


class SentinelVMError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# SDK 发现/缓存/自动更新（移植 abai SentinelSDKManager）
# ---------------------------------------------------------------------------
class SentinelSDK:
    def __init__(self, path: Path, version: str, url: str):
        self.path = path
        self.version = version
        self.url = url


class SentinelSDKManager:
    """从 frame.html 发现最新 SDK 版本并缓存；失败回退内置 sdk.js。"""

    def __init__(self):
        cache_env = os.environ.get("REGIFORGE_SENTINEL_SDK_CACHE", "").strip()
        self.cache_dir = Path(cache_env) if cache_env else (_SDK_DIR / "_cache")
        self.refresh_seconds = 3600.0
        self._lock = threading.Lock()
        self._active: SentinelSDK | None = None
        self._checked_at = 0.0

    @staticmethod
    def _sdk_url(version: str) -> str:
        base = os.environ.get("SENTINEL_BASE_URL", SENTINEL_BASE).rstrip("/")
        return f"{base}/sentinel/{version}/sdk.js"

    @staticmethod
    def _validate(code: str) -> None:
        if len(code) < 1000 or "SentinelSDK" not in code or ".token" not in code:
            raise SentinelVMError("下载的 Sentinel SDK 校验失败")

    @staticmethod
    def _version_of(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _bundled(self) -> SentinelSDK:
        path = _SDK_DIR / "sdk.js"
        version = self._version_of(_SDK_DIR / "version.txt")
        if not path.is_file() or not version:
            raise SentinelVMError("内置 Sentinel SDK 缺失")
        return SentinelSDK(path=path, version=version, url=self._sdk_url(version))

    def _cached(self) -> SentinelSDK | None:
        version = self._version_of(self.cache_dir / "version.txt")
        if not version or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
            return None
        path = self.cache_dir / f"sdk-{version}.js"
        if not path.is_file():
            return None
        try:
            self._validate(path.read_text(encoding="utf-8"))
        except (OSError, SentinelVMError):
            return None
        return SentinelSDK(path=path, version=version, url=self._sdk_url(version))

    def resolve(self, session: Any, log: LogFn | None = None) -> SentinelSDK:
        with self._lock:
            current = self._active or self._cached() or self._bundled()
            now = time.monotonic()
            if self._checked_at and now - self._checked_at < self.refresh_seconds:
                return current
            self._checked_at = now
            discovery = os.environ.get(
                "SENTINEL_SDK_DISCOVERY_URL",
                f"{SENTINEL_BASE}/backend-api/sentinel/frame.html",
            ).strip()
            try:
                fr = session.get(
                    discovery,
                    headers={"accept": "text/html,application/javascript,*/*;q=0.8"},
                    timeout=30,
                )
                if fr.status_code >= 400:
                    raise SentinelVMError(f"frame.html HTTP {fr.status_code}")
                m = _SDK_VERSION_RE.search(fr.text or "")
                if not m:
                    raise SentinelVMError("frame.html 未发现 SDK 版本")
                sdk_url = urljoin(discovery, m.group(1))
                version = m.group(2)
                if current.version == version:
                    self._active = current
                else:
                    ds = session.get(sdk_url, headers={"accept": "*/*"}, timeout=30)
                    if ds.status_code >= 400:
                        raise SentinelVMError(f"sdk 下载失败 HTTP {ds.status_code}")
                    code = ds.text or ""
                    self._validate(code)
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    (self.cache_dir / f"sdk-{version}.js").write_text(
                        code, encoding="utf-8"
                    )
                    (self.cache_dir / "version.txt").write_text(
                        version, encoding="utf-8"
                    )
                    self._active = SentinelSDK(
                        path=self.cache_dir / f"sdk-{version}.js",
                        version=version,
                        url=sdk_url,
                    )
                    if log:
                        log(f"Sentinel V8: sdk 已更新到 {version}")
            except Exception as exc:
                if log:
                    log(f"Sentinel V8: sdk 自动更新失败（用现有缓存）: {str(exc)[:120]}")
                self._active = current
            return self._active


_sdk_manager = SentinelSDKManager()
_sdk_lock = threading.Lock()
_sdk_active: SentinelSDK | None = None


def _resolve_sdk(session, log: LogFn | None = None) -> SentinelSDK:
    """线程安全地解析/刷新 sdk；依赖 manager 内部锁。"""
    global _sdk_active
    sdk = _sdk_manager.resolve(session, log=log)
    with _sdk_lock:
        _sdk_active = sdk
    return sdk


# ---------------------------------------------------------------------------
# V8 worker 池（每时区一个常驻 Node 进程）
# ---------------------------------------------------------------------------
_V8_RUNTIME_DIR = _SDK_DIR


def _worker_count() -> int:
    try:
        n = int(os.environ.get("REGIFORGE_SENTINEL_V8_WORKERS", "3") or 3)
    except ValueError:
        n = 3
    return min(max(n, 1), 8)


def _worker_cap() -> int:
    try:
        n = int(os.environ.get("REGIFORGE_SENTINEL_V8_MAX_WORKERS", "16") or 16)
    except ValueError:
        n = 16
    return min(max(n, _worker_count()), 32)


class _NodeWorker:
    def __init__(self, tz: str, timeout: float = 40.0):
        self.tz = tz or "UTC"
        self.timeout = max(float(timeout or 40.0), 1.0)
        self._lifecycle = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._port = 0
        self._stderr: deque[str] = deque(maxlen=30)

    def _read_stderr(self, proc: subprocess.Popen[str]) -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            self._stderr.append(line.rstrip())

    def _start(self) -> None:
        node = shutil.which(os.environ.get("SENTINEL_NODE_BINARY", "node"))
        if not node:
            raise SentinelVMError("V8 模式需要 Node.js（容器已预装 nodejs）")
        server = _V8_RUNTIME_DIR / "sentinel-server.js"
        if not server.is_file():
            raise SentinelVMError(f"Sentinel V8 server 缺失: {server}")
        env = os.environ.copy()
        env["SENTINEL_SERVER_PORT"] = "0"
        env["SENTINEL_TZ"] = self.tz
        self._stderr.clear()
        proc = subprocess.Popen(
            [node, str(server)],
            cwd=str(_V8_RUNTIME_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._proc = proc
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()

        import queue as _q

        q: "_q.Queue[str]" = _q.Queue(maxsize=1)

        def read_ready() -> None:
            try:
                q.put(proc.stdout.readline() if proc.stdout else "")
            except Exception:
                q.put("")

        threading.Thread(target=read_ready, daemon=True).start()
        try:
            line = q.get(timeout=min(self.timeout, 15.0))
            payload = json.loads(line)
            port = int(payload.get("port") or 0)
            if not payload.get("ready") or port <= 0:
                raise ValueError("invalid ready response")
            self._port = port
        except Exception as exc:
            detail = "; ".join(self._stderr) or "no ready response"
            self._stop()
            raise SentinelVMError(f"V8 worker 启动失败({self.tz}): {detail}") from exc

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        self._port = 0
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        for st in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if st:
                    st.close()
            except OSError:
                pass

    def close(self) -> None:
        with self._lifecycle:
            self._stop()

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None and self._port:
            return
        with self._lifecycle:
            if self._proc is not None and self._proc.poll() is None and self._port:
                return
            self._stop()
            self._start()

    def _request(self, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        conn = http.client.HTTPConnection(
            "127.0.0.1", self._port, timeout=self.timeout
        )
        try:
            conn.request(
                "POST",
                "/token",
                body=body,
                headers={
                    "content-type": "application/json",
                    "content-length": str(len(body)),
                },
            )
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if resp.status >= 400 or not data.get("ok"):
                raise SentinelVMError(
                    str(data.get("error") or f"V8 HTTP {resp.status}")[:400]
                )
            token_text = str(data.get("token") or "")
            token = json.loads(token_text)
            if not isinstance(token, dict):
                raise SentinelVMError("V8 返回非法 token")
            return token
        finally:
            conn.close()

    def execute(self, **payload) -> dict:
        self._ensure()
        try:
            return self._request(payload)
        except SentinelVMError:
            raise
        except (OSError, http.client.HTTPException, json.JSONDecodeError):
            with self._lifecycle:
                self._stop()
                self._start()
            try:
                return self._request(payload)
            except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc2:
                detail = "; ".join(self._stderr) or str(exc2)
                raise SentinelVMError(f"V8 worker 失败: {detail}") from exc2


_pool_lock = threading.Lock()
_pool_by_tz: dict[str, _NodeWorker] = {}
_pool_order: deque[str] = deque()


def _get_worker(tz: str) -> _NodeWorker:
    tz = (tz or "UTC").strip() or "UTC"
    with _pool_lock:
        w = _pool_by_tz.get(tz)
        if w is None:
            if len(_pool_by_tz) >= _worker_cap():
                oldest = _pool_order.popleft()
                old = _pool_by_tz.pop(oldest, None)
                if old is not None:
                    threading.Thread(target=old.close, daemon=True).start()
            w = _NodeWorker(tz=tz)
            _pool_by_tz[tz] = w
            _pool_order.append(tz)
        return w


def close_all_workers() -> None:
    with _pool_lock:
        ws = list(_pool_by_tz.values())
        _pool_by_tz.clear()
        _pool_order.clear()
    for w in ws:
        w.close()


# ---------------------------------------------------------------------------
# Python PoW（移植 abai _SentinelTokenGenerator，环境字段来自 regiforge fp）
# ---------------------------------------------------------------------------
class _PowGenerator:
    def __init__(self, user_agent: str, sdk_url: str, fp: dict[str, Any]):
        self.user_agent = user_agent
        self.sdk_url = sdk_url
        self.sid = str(uuid.uuid4())
        self._fp = fp

    @staticmethod
    def _fnv1a32(text: str) -> str:
        value = 2166136261
        for char in text:
            value ^= ord(char)
            value = (value * 16777619) & 0xFFFFFFFF
        value ^= value >> 16
        value = (value * 2246822507) & 0xFFFFFFFF
        value ^= value >> 13
        value = (value * 3266489909) & 0xFFFFFFFF
        value ^= value >> 16
        return f"{value & 0xFFFFFFFF:08x}"

    @staticmethod
    def _encode(value) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    @property
    def _language(self) -> str:
        return str(self._fp.get("locale") or "en-US")

    @property
    def _languages_str(self) -> str:
        al = str(self._fp.get("accept_language") or "en-US")
        parts = [p.split(";")[0].strip() for p in al.split(",") if p.strip()]
        uniq = list(dict.fromkeys(parts))
        return ",".join(uniq) if uniq else "en-US,en"

    def _reference_fingerprint(self) -> list:
        now = str(datetime.now(zoneinfo.ZoneInfo(self._fp["timezone_id"])))
        w, h = self._fp["screen"]
        perf_now = round(
            time.time() * 1000 - 1_000_000 + random.uniform(1000, 5000), 1
        )
        time_origin = round(time.time() * 1000 - 50_000, 1)
        return [
            3000,
            now,
            4294705152,
            0,
            self.user_agent,
            self.sdk_url,
            None,
            self._language,
            self._languages_str,
            0,
            "webkitTemporaryStorage\u2212undefined",
            "location",
            "Object",
            perf_now,
            self.sid,
            "",
            int(self._fp.get("hardware_concurrency") or 8),
            time_origin,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]

    def _solve_pow(self, seed: str, difficulty: str, data: list) -> str:
        started = time.perf_counter()
        target = str(difficulty or "0")
        for nonce in range(500_000):
            data[3] = nonce
            data[9] = round((time.perf_counter() - started) * 1000)
            encoded = self._encode(data)
            digest = self._fnv1a32(str(seed or "") + encoded)
            if digest[: len(target)] <= target:
                return encoded + "~S"
        return self._encode("e")

    def requirements(self) -> str:
        cfg = self._reference_fingerprint()
        cfg[3] = 1
        cfg[9] = round(5 + random.random() * 45)
        return "gAAAAAC" + self._solve_pow(str(random.random()), "0", cfg)

    def enforcement(self, seed: str, difficulty: str) -> str:
        return "gAAAAAB" + self._solve_pow(
            seed, difficulty, self._reference_fingerprint()
        )


def _looks_like_vm_error(value: str) -> bool:
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4)).decode(
            "utf-8", errors="ignore"
        )
    except Exception:
        return False
    lowered = decoded.lower()
    return "syntaxerror" in lowered or "typeerror" in lowered or "error:" in lowered


# ---------------------------------------------------------------------------
# 对外主入口：纯 HTTP + V8 构建首个 Sentinel 头（不开浏览器）
# ---------------------------------------------------------------------------
def _languages_of(fp: dict[str, Any]) -> str:
    al = str(fp.get("accept_language") or "en-US")
    parts = [p.split(";")[0].strip() for p in al.split(",") if p.strip()]
    uniq = list(dict.fromkeys(parts))
    return ",".join(uniq) if uniq else "en-US"


def _require_curl_cffi():
    try:
        from curl_cffi import requests as curl_requests

        return curl_requests
    except Exception as exc:
        raise SentinelVMError(f"curl_cffi 不可用: {exc}") from exc


def build_first_sentinel_v8(
    *,
    proxy_url: str | None,
    fp: dict[str, Any],
    flow: str | None = None,
    oai_did: str | None = None,
    log: LogFn | None = None,
    timeout: float = 60.0,
) -> dict[str, str]:
    """返回 {"openai-sentinel-token": ..., "openai-sentinel-so-token": ...}
    （只包含实际有值的键）。不开浏览器。"""
    curl_requests = _require_curl_cffi()
    ua = str(fp.get("user_agent") or "")
    if not ua:
        raise SentinelVMError("指纹缺少 user_agent")
    flow = str(flow or os.environ.get("CHATGPT_SENTINEL_FIRST_FLOW", "main"))
    device_id = str(oai_did or uuid.uuid4())
    tz = str(fp.get("timezone_id") or "UTC")

    def _new_session():
        kw: dict[str, Any] = {"impersonate": fp.get("impersonate") or "chrome131"}
        if proxy_url:
            kw["proxies"] = {"http": proxy_url, "https": proxy_url}
        return curl_requests.Session(**kw)

    def _post_req(session, proof: str, referer: str) -> dict:
        r = session.post(
            SENTINEL_REQ_URL,
            data=json.dumps({"p": proof, "id": device_id, "flow": flow}),
            headers={
                "accept": "*/*",
                "content-type": "text/plain;charset=UTF-8",
                "origin": SENTINEL_BASE,
                "referer": referer,
            },
            timeout=timeout,
        )
        try:
            data = r.json()
        except Exception:
            data = {}
        if r.status_code >= 400 or not str((data or {}).get("token") or "").strip():
            raise SentinelVMError(
                f"sentinel/req HTTP {r.status_code}: {str(r.text)[:180]}"
            )
        return data

    # 1) 解析当前 sdk（frame.html 发现 + 缓存 + 内置兜底）
    probe = _new_session()
    try:
        sdk = _resolve_sdk(probe, log=log)
    finally:
        probe.close()

    referer = f"{SENTINEL_BASE}/backend-api/sentinel/frame.html?sv={sdk.version}"
    sess = _new_session()
    try:
        # 2) Python PoW → sentinel/req
        gen = _PowGenerator(ua, sdk.url, fp)
        proof = gen.requirements()
        chat_req = _post_req(sess, proof, referer)

        challenge = str(chat_req.get("token") or "").strip()
        turnstile = chat_req.get("turnstile") or {}
        observer = chat_req.get("so") or {}

        # 3) dx 存在 → V8 沙箱出 token
        vm: dict = {"t": "", "so": ""}
        if turnstile.get("dx") or observer.get("collector_dx") or observer.get("snapshot_dx"):
            vm_challenge = dict(chat_req)
            vm_challenge["_python_proof"] = proof
            w, h = fp.get("screen") or [1920, 1080]
            vm = _get_worker(tz).execute(
                challenge=vm_challenge,
                sdk=str(sdk.path.resolve()),
                script_src=sdk.url,
                user_agent=ua,
                flow=flow,
                device_id=device_id,
                page_url="https://auth.openai.com/about-you",
                width=int(w),
                height=int(h),
                cores=int(fp.get("hardware_concurrency") or 8),
                language=str(fp.get("locale") or "en-US"),
                languages=_languages_of(fp),
                no_cookie=True,
            )
        if turnstile.get("required") and not vm.get("t"):
            raise SentinelVMError("V8 未产出 Turnstile token")

        so_value = str(vm.get("so") or "")
        if so_value and _looks_like_vm_error(so_value):
            so_value = ""

        # 4) PoW enforcement / 首次 proof 兜底
        pow_info = chat_req.get("proofofwork") or {}
        if pow_info.get("required") and pow_info.get("seed"):
            enforcement = gen.enforcement(
                str(pow_info.get("seed") or ""),
                str(pow_info.get("difficulty") or "0"),
            )
        else:
            enforcement = proof
        token = {
            "p": str(vm.get("p") or enforcement),
            "t": str(vm.get("t") or ""),
            "c": challenge,
            "id": device_id,
            "flow": flow,
        }
        headers = {
            "openai-sentinel-token": json.dumps(token, separators=(",", ":"))
        }
        if so_value:
            headers["openai-sentinel-so-token"] = json.dumps(
                {
                    "so": so_value,
                    "c": challenge,
                    "id": device_id,
                    "flow": flow,
                },
                separators=(",", ":"),
            )
        return headers
    finally:
        sess.close()
