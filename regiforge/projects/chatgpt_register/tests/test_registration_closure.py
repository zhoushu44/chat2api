"""注册收口（需求 1）测试：强制设密码 + 强制 TOTP 2FA + 注册后立即验活。

不联网：monkeypatch 掉 _register_sync 内部的各阶段（CSRF/signin/OAuth/OTP/create/session）
与 _register_password / _bind_totp_2fa / session 请求，只验证「三件套强制 + 失败不产出」的收口逻辑。

运行：
    python regiforge/projects/chatgpt_register/tests/test_registration_closure.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许以脚本方式直接运行：把 regiforge 根目录加入 sys.path
_REGIROOT = Path(__file__).resolve().parents[3]
if str(_REGIROOT) not in sys.path:
    sys.path.insert(0, str(_REGIROOT))

from projects.chatgpt_register.steps import _http_engine as eng  # noqa: E402


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text or ""
        self.headers = {}
        self.url = "https://chatgpt.com/"

    def json(self):
        return self._json


class _FakeSession:
    """记录请求；按 URL 关键字返回预设响应，模拟完整注册链。"""

    def __init__(self, *, me_status=200, calls=None):
        self.me_status = me_status
        self.calls = calls if calls is not None else []

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        if "/api/auth/csrf" in url:
            return _FakeResp(200, {"csrfToken": "csrf-xyz"})
        if "/backend-api/me" in url:
            return _FakeResp(self.me_status, {}, "ok" if self.me_status == 200 else "unauthorized")
        if "/api/auth/session" in url:
            return _FakeResp(200, {"accessToken": "AT-1", "sessionToken": "ST-1"})
        return _FakeResp(200, {}, "")

    def post(self, url, **kw):
        self.calls.append(("POST", url))
        if "/api/auth/signin/openai" in url:
            return _FakeResp(200, {"url": "https://auth.openai.com/api/accounts/authorize?x=1"})
        if "/api/accounts/create_account" in url:
            return _FakeResp(200, {"continue_url": "https://chatgpt.com/"})
        return _FakeResp(200, {}, "")

    def close(self):
        pass


def _patch_common(monkeypatch_state: dict, *, pw_ok=True, me_status=200, totp_result=None):
    """把 _register_sync 依赖的所有外部动作替换为可控桩。"""
    calls = []
    session = _FakeSession(me_status=me_status, calls=calls)

    class _ReqCffi:
        def Session(self):
            return session

    eng._require_curl_cffi = lambda: _ReqCffi()
    eng._apply_sentinel_cookies = lambda *a, **k: None
    eng._browser_headers = lambda fp, accept=None: {"User-Agent": "UA"}
    eng._req_kwargs = lambda proxy, fp=None, timeout=None: {}

    eng._csrf_from_response = lambda r: "csrf-xyz"
    # [4] OAuth 跳转：直接返回带 email-verification 的落地
    eng._oauth_get = None  # 未使用（在 _register_sync 内联）

    def _fake_get(url, headers=None, allow_redirects=None, **kw):
        calls.append(("GET", url))
        if "/api/auth/csrf" in url:
            return _FakeResp(200, {"csrfToken": "csrf-xyz"})
        if "/api/auth/session" in url:
            return _FakeResp(200, {"accessToken": "AT-1", "sessionToken": "ST-1"})
        if "/backend-api/me" in url:
            return _FakeResp(me_status, {}, "" if me_status == 200 else "unauthorized")
        # OAuth 首跳：返回带 Location 到 email-verification
        r = _FakeResp(302, {})
        r.headers = {"Location": "https://auth.openai.com/api/accounts/email-verification"}
        r.url = url
        return r

    def _fake_post(url, **kw):
        calls.append(("POST", url))
        if "/api/auth/signin/openai" in url:
            return _FakeResp(200, {"url": "https://auth.openai.com/api/accounts/authorize?x=1"})
        if "/api/accounts/create_account" in url:
            return _FakeResp(200, {"continue_url": "https://chatgpt.com/"})
        return _FakeResp(200, {}, "")

    session.get = _fake_get
    session.post = _fake_post

    eng._register_password = lambda *a, **k: (pw_ok, "tok", "")
    eng._send_otp = lambda *a, **k: True
    eng._resend_otp = lambda *a, **k: True
    eng._wait_new_code = lambda *a, **k: "123456"
    eng._verify_otp_once = lambda *a, **k: (200, {"continue_url": "https://chatgpt.com/"}, "")
    eng._refresh_flow_sentinel = lambda *a, **k: ("tok2", "")
    eng._save_refresh_token = lambda *a, **k: None
    eng.time = eng.time
    # 跳过 OAuth 跟跳循环：让 it 一进入即落到 email-verification
    monkeypatch_state["calls"] = calls
    monkeypatch_state["session"] = session

    if totp_result is None:
        totp_result = {"totp_secret": "SECRET123", "mfa_enabled": True}
    eng._bind_totp_2fa = lambda *a, **k: totp_result


def run_case(name, *, pw_ok=True, totp_result=None, me_status=200, expect_ok=True, expect_msg=""):
    state = {}
    _patch_common(state, pw_ok=pw_ok, me_status=me_status, totp_result=totp_result)
    logs = []
    try:
        out = eng._register_sync(
            email="t@example.com",
            sd={"sentinel_token": "s1", "cookie_str": "", "oai_did": "did"},
            wait_code_sync=lambda addr, **k: "123456",
            proxy_url=None,
            fp={"browser_type": "chrome", "impersonate": "chrome131", "user_agent": "UA",
                "accept_language": "en-US", "locale": "en-US", "timezone_id": "America/New_York",
                "screen_width": 1920, "screen_height": 1080, "hardware_concurrency": 8},
            fetch_refresh_token=False,
            sentinel_refresh=True,
            mail_timeout=30,
            log=logs.append,
        )
    except Exception as exc:  # noqa: BLE001
        if expect_ok:
            print(f"[FAIL] {name}: 预期成功却失败 -> {exc}")
            return False
        if expect_msg and expect_msg not in str(exc):
            print(f"[FAIL] {name}: 失败信息不含 '{expect_msg}' -> {exc}")
            return False
        print(f"[PASS] {name}: 按预期失败 -> {str(exc)[:80]}")
        return True

    if not expect_ok:
        print(f"[FAIL] {name}: 预期失败却成功 -> {out}")
        return False
    if not out.get("password"):
        print(f"[FAIL] {name}: 成功但无 password")
        return False
    if not (out.get("mfa_enabled") and out.get("totp_secret")):
        print(f"[FAIL] {name}: 成功但无 2FA")
        return False
    print(f"[PASS] {name}: 三件套齐活（password+mfa+alive）")
    return True


def _make_ctx(email="t@example.com"):
    from core.base import RunContext
    from core.models import ProxyInfo

    class _Email:
        def generate_address(self):
            return email

        def wait_code(self, addr, timeout=None, **kw):
            async def _c():
                return "123456"
            return _c()

    class _Proxy:
        async def acquire(self):
            return None

        async def release(self, info, failure_type=None):
            return None

    return RunContext(
        task_id="t-test",
        index=1,
        total=1,
        config={"projects": {"chatgpt_register": {"register_mode": "http"}}},
        email=_Email(),
        proxy=_Proxy(),
        captcha=None,
        logger=lambda m: None,
    )


def run_project_closure_case(name, engine_result, *, expect_status):
    """验证 project.py::_run_http 的产出收口（无密码/无 2FA 不得产出 apikey）。"""
    import asyncio

    from projects.chatgpt_register import project as proj

    saved = proj.register_http
    proj.register_http = lambda **kw: _async_return(engine_result)
    try:
        ctx = _make_ctx()
        res = asyncio.run(
            proj.PROJECT._run_http(
                ctx,
                email="t@example.com",
                proxy_info=None,
                sentinel_proxy_info=None,
                user_agent="",
                browser_backend="playwright",
                mail_timeout=30,
                fetch_refresh=True,
            )
        )
    finally:
        proj.register_http = saved

    if res.status != expect_status:
        print(f"[FAIL] {name}: status={res.status} 预期={expect_status} err={res.error[:60]}")
        return False
    if expect_status != "ok" and res.apikey:
        print(f"[FAIL] {name}: 失败路径却产出了 apikey")
        return False
    if expect_status == "ok" and not res.apikey:
        print(f"[FAIL] {name}: 成功路径却无 apikey")
        return False
    print(f"[PASS] {name}: status={res.status} apikey={'有' if res.apikey else '无'}")
    return True


def _async_return(value):
    async def _inner(**kw):
        return value
    return _inner()


def main() -> int:
    results = []

    # T1/T2：强制生效（不依赖任何配置开关，函数签名已无 set_password/bind_2fa 参数）
    import inspect
    sig = inspect.signature(eng._register_sync)
    no_switch = "set_password" not in sig.parameters and "bind_2fa" not in sig.parameters
    print(f"[{'PASS' if no_switch else 'FAIL'}] T1 配置开关已移除（_register_sync 签名无 set_password/bind_2fa）")
    results.append(no_switch)

    # T6：正常路径三件套齐活
    results.append(run_case("T6 正常路径", expect_ok=True))

    # T3：设密码失败 → 判失败
    results.append(run_case("T3 设密码失败", pw_ok=False, expect_ok=False, expect_msg="设密码失败"))

    # T4：2FA 绑定失败（含幂等拿不到 secret）→ 判失败
    results.append(run_case("T4a 2FA 绑定返回空", totp_result={}, expect_ok=False, expect_msg="绑定 TOTP 2FA 失败"))
    results.append(run_case("T4b 2FA 幂等无 secret", totp_result={"mfa_enabled": False}, expect_ok=False, expect_msg="绑定 TOTP 2FA 失败"))

    # T5：验活失败 → 判失败
    results.append(run_case("T5 验活 401", me_status=401, expect_ok=False, expect_msg="验活失败"))

    # T1(收口层)：project.py 产出收口
    base = {"email": "t@example.com", "access_token": "AT-1", "password": "Pw1!", "totp_secret": "S1", "mfa_enabled": True, "plan_type": "free"}
    results.append(run_project_closure_case("T6' 收口层-齐活", dict(base), expect_status="ok"))
    results.append(run_project_closure_case("T3' 收口层-无密码", {**base, "password": ""}, expect_status="fail_http_no_password"))
    results.append(run_project_closure_case("T4' 收口层-无2FA", {**base, "mfa_enabled": False, "totp_secret": ""}, expect_status="fail_http_no_2fa"))

    ok = all(results)
    print("-" * 50)
    print(f"结果：{sum(results)}/{len(results)} 通过")
    return 0 if ok else 1



if __name__ == "__main__":
    raise SystemExit(main())
