"""FlareSolverr 通用工具函数。

提供简单的 API 供任何项目调用 FlareSolverr 服务。
"""
from __future__ import annotations

import json
from typing import Any

from .provider import FlareSolverrProvider

# 全局单例（延迟初始化）
_provider: FlareSolverrProvider | None = None


def get_provider() -> FlareSolverrProvider:
    """获取 FlareSolverr Provider 单例。

    Returns:
        配置好的 FlareSolverrProvider 实例
    """
    global _provider
    if _provider is None:
        _provider = FlareSolverrProvider()
    return _provider


def configure(config: dict[str, Any] | None = None) -> None:
    """配置 FlareSolverr 服务。

    Args:
        config: 配置字典，包含：
            - api_url: FlareSolverr API 地址
            - proxy: 代理配置（可选）
            - max_timeout: 最大超时（毫秒）

    示例：
        configure({
            "api_url": "http://192.6.121.16:8191/v1",
            "proxy": {
                "url": "socks5://mihomo:7890",
                "username": "user",
                "password": "pass"
            },
            "max_timeout": 60000
        })
    """
    provider = get_provider()
    provider.configure(config)


async def solve_cloudflare(
    page_url: str,
    sitekey: str = "",
    *,
    api_url: str | None = None,
    proxy: dict[str, Any] | None = None,
    max_timeout: int | None = None,
) -> dict[str, Any] | None:
    """调用 FlareSolverr 解决 Cloudflare 挑战。

    这是最常用的函数，适用于任何需要过 Cloudflare 的场景。

    Args:
        page_url: 目标页面 URL
        sitekey: Cloudflare sitekey（可选）
        api_url: FlareSolverr API 地址（可选，覆盖全局配置）
        proxy: 代理配置（可选，覆盖全局配置）
        max_timeout: 最大超时毫秒（可选，覆盖全局配置）

    Returns:
        字典，包含：
            - cf_clearance: Cloudflare clearance Cookie
            - ua: User-Agent
            - cookies: 完整 Cookie 列表
            - response: 页面 HTML
            - url: 最终 URL
            - status: HTTP 状态码
        失败返回 None

    示例：
        # 基础调用
        result = await solve_cloudflare("https://auth.openai.com/")
        if result:
            print(f"cf_clearance: {result['cf_clearance']}")
            print(f"User-Agent: {result['ua']}")

        # 带代理调用
        result = await solve_cloudflare(
            "https://auth.openai.com/",
            proxy={
                "url": "socks5://mihomo:7890",
                "username": "user",
                "password": "pass"
            }
        )

        # 动态指定服务地址
        result = await solve_cloudflare(
            "https://example.com",
            api_url="http://其他服务器：8191/v1"
        )
    """
    provider = get_provider()

    # 构建运行时参数
    kwargs = {}
    if api_url:
        kwargs["api_url"] = api_url
    if proxy:
        kwargs["proxy"] = proxy
    if max_timeout:
        kwargs["max_timeout"] = max_timeout

    # 调用 Provider
    result = await provider.solve(
        sitekey=sitekey,
        page_url=page_url,
        **kwargs,
    )

    if not result:
        return None

    # 解析 JSON 并返回字典
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return None


def apply_to_session(
    session: Any,
    result: dict[str, Any],
    set_cookies: bool = True,
) -> None:
    """将 FlareSolverr 返回结果应用到 requests 会话。

    Args:
        session: requests.Session 或类似对象
        result: solve_cloudflare 返回的字典
        set_cookies: 是否设置 Cookie

    示例：
        import requests
        result = await solve_cloudflare("https://example.com")
        session = requests.Session()
        apply_to_session(session, result)

        # 现在可以用 session 继续访问了
        response = session.get("https://example.com/protected")
    """
    if not result:
        return

    # 设置 User-Agent
    if "ua" in result and result["ua"]:
        if hasattr(session, "headers"):
            session.headers["User-Agent"] = result["ua"]

    # 设置 Cookie
    if set_cookies and "cookies" in result:
        for cookie_data in result["cookies"]:
            if not isinstance(cookie_data, dict):
                continue

            name = cookie_data.get("name", "")
            value = cookie_data.get("value", "")
            domain = cookie_data.get("domain", "")
            path = cookie_data.get("path", "/")

            if not name or not value:
                continue

            if hasattr(session, "cookies"):
                # requests.Session
                from http.cookiejar import Cookie

                cookie = Cookie(
                    version=0,
                    name=name,
                    value=value,
                    port=None,
                    port_specified=False,
                    domain=domain or "",
                    domain_specified=bool(domain),
                    domain_initial_dot=domain.startswith("."),
                    path=path or "/",
                    path_specified=True,
                    secure=cookie_data.get("secure", False),
                    expires=cookie_data.get("expiry"),
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                )
                session.cookies.set_cookie(cookie)


# 兼容性别名
solve = solve_cloudflare
