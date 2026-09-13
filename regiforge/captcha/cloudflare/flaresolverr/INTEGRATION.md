# FlareSolverr 集成指南

本文档说明如何在项目中集成 FlareSolverr 服务来绕过 Cloudflare 挑战。

## 快速开始

### 1. 最简单的调用方式

```python
from captcha.cloudflare.flaresolverr import solve_cloudflare

# 调用 FlareSolverr
result = await solve_cloudflare(
    "https://auth.openai.com/",
    proxy={
        "url": "socks5://192.6.121.16:7890"
    }
)

if result:
    # 获取关键信息
    cf_clearance = result["cf_clearance"]
    user_agent = result["ua"]
    cookies = result["cookies"]
    
    print(f"✅ 挑战通过！cf_clearance: {cf_clearance[:50]}...")
else:
    print("❌ 挑战失败")
```

### 2. 在项目中集成

#### 方式一：在 HTTP 引擎中使用（ChatGPT HTTP 模式）

```python
# projects/chatgpt_register/steps/_http_engine.py
from captcha.cloudflare.flaresolverr import solve_cloudflare

async def _handle_cloudflare_challenge(
    page_url: str,
    proxy_info: ProxyInfo | None,
) -> tuple[str, str] | None:
    """处理 Cloudflare 挑战。
    
    Returns:
        (cf_clearance, user_agent) 或 None
    """
    # 构建代理配置
    proxy_config = None
    if proxy_info and proxy_info.server:
        proxy_config = {
            "url": proxy_info.server,
            "username": proxy_info.username,
            "password": proxy_info.password,
        }
    
    # 调用 FlareSolverr
    result = await solve_cloudflare(
        page_url,
        proxy=proxy_config,
        max_timeout=60000,
    )
    
    if not result:
        return None
    
    return result["cf_clearance"], result["ua"]
```

#### 方式二：在浏览器模式中使用（辅助过 Cloudflare）

```python
# projects/chatgpt_register/steps/_browser.py
from captcha.cloudflare.flaresolverr import solve_cloudflare, apply_to_session
import requests

async def _bypass_cloudflare_with_flaresolverr(
    page_url: str,
    proxy_info: ProxyInfo | None,
) -> requests.Session | None:
    """使用 FlareSolverr 绕过 Cloudflare，返回配置好的会话。
    
    适用于：
    - 浏览器启动前需要先过 Cloudflare
    - 提取 Cookie 后注入到浏览器
    """
    proxy_config = None
    if proxy_info and proxy_info.server:
        proxy_config = {
            "url": proxy_info.server,
            "username": proxy_info.username,
            "password": proxy_info.password,
        }
    
    result = await solve_cloudflare(page_url, proxy=proxy_config)
    if not result:
        return None
    
    # 创建会话并应用结果
    session = requests.Session()
    apply_to_session(session, result)
    
    return session
```

#### 方式三：统一 Challenge 处理模块

```python
# projects/chatgpt_register/steps/_challenge.py
from __future__ import annotations
from typing import Any
from captcha.cloudflare.flaresolverr import solve_cloudflare

class CloudflareChallenge:
    """Cloudflare 挑战处理器。"""
    
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
    
    async def solve(
        self,
        page_url: str,
        use_flaresolverr: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """解决 Cloudflare 挑战。
        
        Args:
            page_url: 目标页面 URL
            use_flaresolverr: 是否使用 FlareSolverr
            **kwargs: 传递给 solve_cloudflare 的参数
        
        Returns:
            包含 cf_clearance、ua、cookies 的字典
        """
        if use_flaresolverr:
            return await solve_cloudflare(page_url, **kwargs)
        
        # 其他挑战解决方式...
        return None
```

### 3. 完整项目集成示例

以 ChatGPT 注册项目为例：

```python
# projects/chatgpt_register/steps/step01_open_login.py
from __future__ import annotations
from playwright.async_api import Page
from core.step_debug import RegisterDebug
from captcha.cloudflare.flaresolverr import solve_cloudflare

async def step01_open_login(
    page: Page,
    context: RegisterDebug,
    **kwargs,
) -> bool:
    """步骤 1: 打开登录页面（带 Cloudflare 挑战处理）。"""
    
    # 先尝试直接访问
    await page.goto("https://auth.openai.com/", wait_until="domcontentloaded")
    
    # 检测是否遇到 Cloudflare
    if await _is_cloudflare_page(page):
        context.log("检测到 Cloudflare 挑战，使用 FlareSolverr...")
        
        # 获取代理配置
        proxy_info = await context.proxy.acquire() if context.proxy else None
        
        try:
            # 调用 FlareSolverr
            result = await solve_cloudflare(
                "https://auth.openai.com/",
                proxy={
                    "url": proxy_info.server,
                    "username": proxy_info.username,
                    "password": proxy_info.password,
                } if proxy_info else None,
            )
            
            if result:
                context.log(f"✅ Cloudflare 通过：{result['cf_clearance'][:50]}...")
                
                # 注入 Cookie 到浏览器
                await _inject_cookies(page, result["cookies"])
                
                # 重新加载页面
                await page.reload(wait_until="domcontentloaded")
                
                # 验证是否成功
                if not await _is_cloudflare_page(page):
                    context.log("✅ 成功绕过 Cloudflare")
                    return True
        
        finally:
            # 释放代理
            if proxy_info and context.proxy:
                await context.proxy.release(proxy_info)
        
        # FlareSolverr 失败，尝试其他方式或报错
        context.log("⚠️ FlareSolverr 失败，尝试直接访问...")
    
    # 检查是否成功到达登录页
    return await _is_login_page(page)


async def _is_cloudflare_page(page: Page) -> bool:
    """检测是否是 Cloudflare 挑战页面。"""
    try:
        # 检查是否有 Cloudflare 特征元素
        cf_selector = (
            "div.cf-browser-verification,"
            "iframe[src*='cf-chl-bounce'],"
            "title:text('Just a moment...')"
        )
        return await page.query_selector(cf_selector) is not None
    except Exception:
        return False


async def _inject_cookies(page: Page, cookies: list[dict]) -> None:
    """注入 Cookie 到浏览器。"""
    for cookie_data in cookies:
        if not isinstance(cookie_data, dict):
            continue
        
        cookie = {
            "name": cookie_data.get("name", ""),
            "value": cookie_data.get("value", ""),
            "domain": cookie_data.get("domain", ""),
            "path": cookie_data.get("path", "/"),
            "httpOnly": cookie_data.get("httpOnly", False),
            "secure": cookie_data.get("secure", False),
        }
        
        if cookie["name"] and cookie["value"]:
            await page.context.add_cookies([cookie])
```

## 配置方式

### 方式一：Web 控制台配置

1. 打开 Web 控制台
2. 选择验证码 Provider 为 `FlareSolverr (远程服务)`
3. 填写配置：
   - FlareSolverr API 地址：`http://192.6.121.16:8191/v1`
   - 代理地址（可选）：`socks5://mihomo:7890`
   - 代理用户名/密码（可选）
   - 最大超时：`60000`

### 方式二：代码配置

```python
from captcha.cloudflare.flaresolverr import configure

configure({
    "api_url": "http://192.6.121.16:8191/v1",
    "proxy": {
        "url": "socks5://mihomo:7890",
        "username": "user",
        "password": "pass"
    },
    "max_timeout": 60000
})
```

### 方式三：配置文件

在 `data/config.json` 中添加：

```json
{
  "captcha": {
    "cloudflare": {
      "flaresolverr": {
        "api_url": "http://192.6.121.16:8191/v1",
        "proxy": {
          "url": "socks5://mihomo:7890",
          "username": "user",
          "password": "pass"
        },
        "max_timeout": 60000
      }
    }
  }
}
```

## 高级用法

### 1. 动态指定服务地址

```python
# 为不同的网站使用不同的 FlareSolverr 实例
result1 = await solve_cloudflare(
    "https://site1.com",
    api_url="http://server1:8191/v1"
)

result2 = await solve_cloudflare(
    "https://site2.com",
    api_url="http://server2:8191/v1"
)
```

### 2. 多个代理轮换

```python
proxies = [
    {"url": "socks5://proxy1:7890"},
    {"url": "socks5://proxy2:7890"},
    {"url": "socks5://proxy3:7890"},
]

for proxy in proxies:
    result = await solve_cloudflare(
        "https://target.com",
        proxy=proxy
    )
    if result:
        break
else:
    raise RuntimeError("所有代理都失败")
```

### 3. 与 Playwright 浏览器配合

```python
from playwright.async_api import async_playwright
from captcha.cloudflare.flaresolverr import solve_cloudflare

async with async_playwright() as p:
    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    
    # 先用 FlareSolverr 过 Cloudflare
    result = await solve_cloudflare("https://target.com")
    
    if result:
        # 注入 Cookie
        await context.add_cookies([
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
            }
            for c in result["cookies"]
            if c.get("name") and c.get("value")
        ])
        
        # 设置 User-Agent
        await context.set_extra_http_headers({
            "User-Agent": result["ua"]
        })
        
        # 访问目标页面
        await page.goto("https://target.com")
```

## 测试

### 单元测试

```python
# tests/test_flaresolverr.py
import pytest
from captcha.cloudflare.flaresolverr import solve_cloudflare

@pytest.mark.asyncio
async def test_solve_cloudflare_basic():
    """测试基础调用。"""
    result = await solve_cloudflare("https://www.google.com")
    assert result is not None
    assert "cf_clearance" in result or "cookies" in result

@pytest.mark.asyncio
async def test_solve_cloudflare_with_proxy():
    """测试带代理调用。"""
    result = await solve_cloudflare(
        "https://auth.openai.com/",
        proxy={
            "url": "socks5://192.6.121.16:7890"
        }
    )
    assert result is not None
    assert "ua" in result
    assert "cookies" in result
```

### 真实测试

```bash
# 测试脚本
python -c "
import asyncio
from captcha.cloudflare.flaresolverr import solve_cloudflare

async def test():
    result = await solve_cloudflare(
        'https://auth.openai.com/',
        proxy={'url': 'socks5://192.6.121.16:7890'}
    )
    if result:
        print('✅ 成功！')
        print(f'cf_clearance: {result[\"cf_clearance\"][:50]}...')
        print(f'User-Agent: {result[\"ua\"][:80]}...')
        print(f'Cookies: {len(result[\"cookies\"])} 个')
    else:
        print('❌ 失败！')

asyncio.run(test())
"
```

## 故障排查

### Q1: 服务无法连接
```python
# 检查 FlareSolverr 是否运行
curl http://192.6.121.16:8191/v1 -X POST \
  -H "Content-Type: application/json" \
  -d '{"cmd":"request.get","url":"https://www.google.com"}'
```

### Q2: 挑战超时
```python
# 增加超时时间
result = await solve_cloudflare(
    "https://target.com",
    max_timeout=120000  # 增加到 120 秒
)
```

### Q3: 代理失败
```python
# 尝试不使用代理
result = await solve_cloudflare(
    "https://target.com",
    proxy=None  # 不使用代理
)

# 或更换代理
result = await solve_cloudflare(
    "https://target.com",
    proxy={"url": "socks5://其他代理：7890"}
)
```

## 最佳实践

1. **优先使用远程服务**：本地不运行浏览器，节省资源
2. **配合 mihomo 使用**：统一管理代理，支持动态切换
3. **设置合理的超时**：根据网络情况调整 `max_timeout`
4. **失败重试机制**：实现重试逻辑，提高成功率
5. **日志记录**：记录每次调用的结果和错误
6. **Cookie 管理**：妥善保存和复用 Cookie，避免重复挑战

## 相关文档

- [FlareSolverr Docker 部署教程](../../C:/知识库/史蒂夫周/注册机/FlareSolverr%20Docker%20部署教程.md)
- [FlareSolverr Provider README](./README.md)
