# NVIDIA HTTP 模式 - 最终结论

**测试日期**: 2026-08-03  
**代理**: socks5://sockstest:socks-pass%401@192.6.121.16:7890 ✅ 正常

---

## 📊 测试结果

### ❌ 纯 HTTP 模式不可行

**原因**: **build.nvidia.com 有 Cloudflare 保护**

```
[步骤 1] 访问 build.nvidia.com 获取 key...
build.nvidia.com HTTP 202
❌ 步骤 1 失败：Cloudflare 挑战（需要 Browser 模式）
```

**HTTP 202** = Cloudflare 的挑战响应，说明：
- curl_cffi 的 Chrome 145 指纹不足以绕过
- 需要执行 JavaScript 才能通过挑战
- 纯 HTTP 模式无法处理

---

## 💡 唯一可行方案：混合模式

### 流程

```
Browser 模式（Playwright）
  ↓
访问 build.nvidia.com（自动处理 Cloudflare）
  ↓
提取 key 参数和 Cookie
  ↓
切换到 HTTP 模式（curl_cffi）
  ↓
使用 key + Cookie 访问 NVGS
  ↓
完成后续注册流程（快速）
  ↓
获取 API Key
```

### 为什么必须混合？

| 步骤 | 域名 | 挑战 | 解决方案 |
|------|------|------|----------|
| **1. 获取 key** | build.nvidia.com | **Cloudflare** | **必须 Browser** |
| 2. 提交邮箱 | login.nvidia.com | key 参数 | HTTP（带 key） |
| 3. 注册表单 | login.nvidia.com | hCaptcha | HTTP + 打码 |
| 4. OTP 验证 | login.nvidia.com | - | HTTP |
| 5. Post-Verification | consent/login/cloudaccounts | - | HTTP |
| 6. API Key | api.ngc.nvidia.com | - | HTTP |

**关键**: 步骤 1 必须用 Browser，后续可以用 HTTP。

---

## 📋 实现计划

### 方案 A: 混合模式（推荐）

**修改 `project.py`**:

```python
async def _run_hybrid(self, ctx, email, password):
    """混合模式：Browser 获取 key + HTTP 完成注册"""
    
    # 步骤 1: Browser 获取 key 和 Cookie
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 访问 build.nvidia.com
        await page.goto("https://build.nvidia.com/?modal=signin")
        await page.wait_for_timeout(5000)  # 等 Cloudflare 通过
        
        # 提取 key
        key = await page.evaluate("""() => {
            if (window.__INITIAL_STATE__) {
                return window.__INITIAL_STATE__.key;
            }
            return null;
        }""")
        
        # 获取 Cookie
        cookies = await context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        
        await browser.close()
        
        if not key:
            return await dbg.fail(..., error="无法获取 key")
        
        ctx.log(f"获取到 key: {key[:20]}...")
    
    # 步骤 2: HTTP 模式完成注册
    from ._http_engine_v2 import NvHTTPClient
    
    client = NvHTTPClient(proxy=proxy)
    client._key = key
    client._cookies = cookie_dict
    
    # 继续后续步骤...
    # submit_email → submit_registration → submit_otp → ...
```

**优点**:
- ✅ 利用 Browser 处理 Cloudflare（稳定）
- ✅ 利用 HTTP 处理后续步骤（快速）
- ✅ 速度 1-2 分钟/账号
- ✅ 并发 10-20

**缺点**:
- 📋 需要实现混合逻辑
- 📋 需要提取 key 和 Cookie 的逻辑

### 方案 B: 纯 Browser 模式（立即可用）

**状态**: ✅ 已完整实现

**使用**:
```bash
# Web 控制台
register_mode = "browser"
```

**优点**:
- ✅ 稳定可靠
- ✅ 已验证可用
- ✅ 自动处理 Cloudflare

**缺点**:
- 速度慢（2-3 分钟/账号）
- 并发低（4-8）
- 资源占用高

---

## 🎯 建议

### 立即行动

**使用 Browser 模式**进行实际注册：
```bash
register_mode = "browser"
```

- ✅ 稳定可靠，已验证可用
- ✅ 可以升到 L4（Web 控制台批量并发）

### 中期开发

**实现混合模式**提高速度：
1. 修改 `project.py` 添加 `_run_hybrid()` 方法
2. 实现 Browser 提取 key 和 Cookie
3. 使用 HTTP 引擎完成后续步骤
4. 逐级验收 L1→L2→L3→L4

**预期效果**:
- 速度：1-2 分钟/账号（vs Browser 的 2-3 分钟）
- 并发：10-20（vs Browser 的 4-8）

---

## 📁 相关文件

```
projects/nvidia_build/
├── steps/
│   ├── _http_engine_v2.py       [✅] HTTP 引擎 v2（完整）
│   └── _flow.py                 [✅] Browser 模式流程
├── project.py                   [需要修改] 添加混合模式
├── test_http_v2.py              [✅] HTTP v2 测试
└── HTTP_FINAL_CONCLUSION.md     [✅] 本文档
```

---

## 📞 结论

**纯 HTTP 模式不可行**，因为 build.nvidia.com 有 Cloudflare 保护。

**唯一可行方案**: 混合模式（Browser + HTTP）

**立即可用**: Browser 模式（register_mode="browser"）

---

**更新**: 2026-08-03  
**状态**: HTTP 引擎 v2 框架完整，但需要 Browser 处理 Cloudflare
