from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .models import ProxyInfo


ContextSetup = Callable[[Any], Awaitable[None]]

BROWSER_BACKEND_PLAYWRIGHT = "playwright"
BROWSER_BACKEND_PATCHRIGHT = "patchright"
BROWSER_BACKENDS = (BROWSER_BACKEND_PLAYWRIGHT, BROWSER_BACKEND_PATCHRIGHT)

# 隐藏 Playwright 自动化标识的 JS 注入脚本——在所有页面创建前执行。
# xAI/Grok 等 Cloudflare 保护的站点会检测 navigator.webdriver，
# 以及 window.chrome 对象缺失等指纹来判断是否为自动化浏览器。
# Patchright 已修 CDP 泄漏；JS 层补丁对两种底座仍有帮助，统一注入。
# 注意：只对顶层窗口注入。Arkose HUMAN 挑战帧（hsprotect/px-cdn/arkoselabs）
# 会检测这些 JS hook 本身，注入反而导致挑战不渲染；iframe 创建时会先以
# about:blank 出现，hostname 判断不可靠，故用 window.top 判定。
_STEALTH_JS = """
(() => {
  // 只注入顶层窗口；iframe（如 Arkose 挑战帧）保持原生环境
  if (window.top !== window.self) {
    return;
  }
// 1. 删除 navigator.webdriver 属性，防止 Cloudflare 等检测
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 2. 补齐 window.chrome 对象（Playwright 默认不注入，而真实 Chrome 有）
if (!window.chrome) {
    window.chrome = {};
}
if (!window.chrome.runtime) {
    window.chrome.runtime = { connect: function(){}, sendMessage: function(){} };
}

// 3. 覆盖 permissions query，防止检测 notification 权限差异
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// 4. 修补 plugins/mimeTypes 长度（有头 Chrome 应有值）
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
});
})();
"""


def normalize_browser_backend(value: str | None) -> str:
    """归一化底座 ID：playwright | patchright。"""
    raw = str(value or "").strip().lower()
    if raw in ("", "default", "pw", "stock"):
        return BROWSER_BACKEND_PLAYWRIGHT
    if raw in ("patchright", "patch", "pr"):
        return BROWSER_BACKEND_PATCHRIGHT
    if raw in BROWSER_BACKENDS:
        return raw
    return BROWSER_BACKEND_PLAYWRIGHT


def resolve_browser_backend(
    config: dict[str, Any] | None = None,
    *,
    project_id: str | None = None,
    explicit: str | None = None,
) -> str:
    """解析浏览器底座：显式参数 > 项目配置 > 全局 browser.backend > playwright。"""
    if explicit is not None and str(explicit).strip():
        return normalize_browser_backend(explicit)
    cfg = config or {}
    if project_id:
        project_cfg = (cfg.get("projects") or {}).get(project_id) or {}
        project_backend = project_cfg.get("browser_backend")
        if project_backend is not None and str(project_backend).strip():
            return normalize_browser_backend(str(project_backend))
    global_backend = (cfg.get("browser") or {}).get("backend")
    if global_backend is not None and str(global_backend).strip():
        return normalize_browser_backend(str(global_backend))
    return BROWSER_BACKEND_PLAYWRIGHT


def get_async_playwright(backend: str | None = None):
    """返回对应底座的 async_playwright() 工厂调用结果（async context manager）。"""
    backend_id = normalize_browser_backend(backend)
    if backend_id == BROWSER_BACKEND_PATCHRIGHT:
        try:
            from patchright.async_api import async_playwright as _async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "浏览器底座 patchright 未安装。请执行: pip install patchright"
            ) from exc
        return _async_playwright()
    from playwright.async_api import async_playwright as _async_playwright

    return _async_playwright()


def _system_chrome_path() -> str | None:
    candidates = (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/chromium"),
    )
    return next((str(path) for path in candidates if path.exists()), None)


@asynccontextmanager
async def browser_session(
    *,
    proxy_info: ProxyInfo | None = None,
    browser_channel: str = "chrome",
    browser_backend: str = BROWSER_BACKEND_PLAYWRIGHT,
    user_agent: str = "",
    setup_context: ContextSetup | None = None,
) -> AsyncIterator[tuple[Any, Any]]:
    """启动一个有头、持久且仅含一个前置页面的 Chrome 会话。

    browser_backend:
      - playwright：原版 Playwright（默认）
      - patchright：CDP 泄漏修补的 Playwright fork（需 pip install patchright）

    内建反自动化检测措施：
    - 禁用 AutomationControlled 特性（去掉 navigator.webdriver 标记）
    - 通过 add_init_script 注入 JS 隐藏自动化指纹
    - 使用系统 Chrome 可执行文件时设置合理的 User-Agent
    """
    backend_id = normalize_browser_backend(browser_backend)
    launch: dict = {
        "headless": False,
        # 保留大部分默认参数，只去掉 --no-startup-window（确保窗口可见）
        # 和 --enable-automation（避免显示"Chrome 正受到自动化测试软件的控制"提示）
        "ignore_default_args": ["--no-startup-window", "--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-quic",
            "--start-maximized",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }
    chrome_path = _system_chrome_path()
    # 使用系统 Chrome 可执行文件，恢复 Grok 历史成功路径；
    # 只有未找到本机 Chrome 时才使用 channel 映射。
    channel = (browser_channel or "").strip()
    if chrome_path:
        launch["executable_path"] = chrome_path
    elif channel:
        launch["channel"] = channel
    if proxy_info:
        pw_proxy = proxy_info.to_playwright()
        if pw_proxy:
            launch["proxy"] = pw_proxy
        # Chrome 不支持 socks5h:// 协议前缀，无法告知"由代理端做 DNS 解析"。
        # 通过 --host-resolver-rules 让所有域名解析返回 ~NOTFOUND，
        # 迫使 Chrome 将原始主机名（而非已解析 IP）发送给 SOCKS5 代理，
        # 等效于 socks5h 的远程 DNS 解析行为。
        is_local_forwarder = bool((proxy_info.meta or {}).get("upstream"))
        if proxy_info.server.lower().startswith("socks5://") and not is_local_forwarder:
            from urllib.parse import urlparse
            parsed = urlparse(proxy_info.server)
            host = (parsed.hostname or "").strip()
            extra = f", EXCLUDE {host}" if host and host not in {"127.0.0.1", "localhost"} else ""
            launch["args"].append(
                f"--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1{extra}"
            )
            # 如果 SOCKS5 代理需要认证，尝试通过 --proxy-server 传递
            # 注意：Chrome 对 SOCKS5 认证支持有限，可能需要本地代理中转
            from urllib.parse import urlparse
            parsed = urlparse(proxy_info.server)
            if parsed.username and parsed.password:
                # 含认证的 SOCKS5，Chrome 可能不支持
                # 添加警告日志
                print(f"[WARN] SOCKS5 代理包含认证，但 Chrome 可能不支持。如失败请使用本地代理中转或免认证代理。")

    context_options: dict = {"ignore_https_errors": True, "viewport": None}
    # 仅在用户明确配置时覆盖 UA；否则让实际 Chrome 自己生成版本一致的 UA。
    # 硬编码版本会造成 UA 与系统 Chrome 不一致，增加 Cloudflare 风控。
    if user_agent:
        context_options["user_agent"] = user_agent

    with TemporaryDirectory(prefix="nvkeyforge-browser-", ignore_cleanup_errors=True) as profile_dir:
        async with get_async_playwright(backend_id) as playwright:
            use_ephemeral = backend_id == BROWSER_BACKEND_PATCHRIGHT and bool(
                proxy_info and (proxy_info.meta or {}).get("upstream")
            )
            browser = None
            if use_ephemeral:
                launch.pop("executable_path", None)
                launch["channel"] = channel or "chrome"
                browser = await playwright.chromium.launch(**launch)
                context = await browser.new_context(**context_options)
            else:
                context = await playwright.chromium.launch_persistent_context(
                    profile_dir, **launch, **context_options
                )
            # 注入反自动化检测脚本——对所有新页面自动生效
            await context.add_init_script(_STEALTH_JS)
            try:
                if setup_context:
                    await setup_context(context)
                page = context.pages[0] if context.pages else await context.new_page()
                await page.bring_to_front()
                yield context, page
            finally:
                await context.close()
                if browser is not None:
                    await browser.close()
