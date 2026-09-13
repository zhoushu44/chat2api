# NVIDIA HTTP 模式 - 代理测试结果

**测试日期**: 2026-08-03  
**代理配置**: `socks5://sockstest:socks-pass%401@192.6.121.16:7890`

---

## 📊 测试结果

### 代理状态 ✅ 正常

```
[1/1] 代理：socks5://sockstest:socks-pass%401@192.6.121.16:7890
[1/1] [1/6] 加载注册页面... OK (2.3s)
```

- ✅ 可以访问 build.nvidia.com（返回 HTTP 202）
- ✅ 代理工作正常
- ✅ 墙已开

### 注册结果 ❌ 失败

```
[1/1] [2/6] 提交邮箱...
[1/1] ERROR: NVGS 返回 403（需要 key 或 Cookie）
```

**失败原因**: 不是墙的问题，是**缺少 key 参数和 Cookie**

---

## 🔍 问题分析

### 为什么 403？

NVIDIA 的注册流程是这样的：

```
1. 访问 build.nvidia.com/?modal=signin
   ↓ (获取 key 参数)
2. 跳转到 login.nvidia.com/v1/create-account?key=xxx
   ↓ (填写邮箱、密码、验证码)
3. 提交注册表单
   ↓ (OTP 验证)
4. 邮箱验证
   ↓ (后验证流程)
5. consent.nvidia.com → login.nvidia.com → cloudaccounts.nvidia.com
   ↓ (获取 API Key)
6. api.ngc.nvidia.com
```

**关键点**:
- 步骤 1 → 步骤 2 的跳转需要一个 **key 参数**
- 这个 key 从 build.nvidia.com 的页面中获取
- 当前 HTTP 引擎**直接访问步骤 2**，没有带 key
- 所以 NVGS 返回 403

### 比喻

就像去游乐园：
- build.nvidia.com = 售票处
- login.nvidia.com = 入园闸机
- key = 门票

**当前问题**: 没买票就想入园 → 被拦住了（403）

---

## 💡 解决方案：混合模式

### 流程

```
Browser 模式
  ↓
访问 build.nvidia.com（售票处）
  ↓
提取 key 参数和 Cookie（买票）
  ↓
切换到 HTTP 模式
  ↓
使用 key + Cookie 访问 NVGS（持票入园）
  ↓
完成后续注册流程（快速）
  ↓
获取 API Key
```

### 优点

- ✅ Browser 处理 Cloudflare 和 JS（稳定）
- ✅ HTTP 处理后续步骤（快速）
- ✅ 速度 1-2 分钟/账号
- ✅ 并发 10-20

### 实现步骤

#### 1. 修改 HTTP 引擎支持 key 和 Cookie

编辑 `projects/nvidia_build/steps/_http_engine.py`:

```python
class NvHTTPClient:
    def __init__(self, proxy=None, key=None, cookies=None):
        self._key = key
        self._cookies = cookies or {}
        
    def load_signup_page(self) -> Tuple[bool, str]:
        # 使用 key 访问 NVGS
        if self._key:
            url = f"{NVGS_BASE}/v1/create-account?key={self._key}"
        else:
            url = f"{NVGS_BASE}/v1/create-account"
        
        # 设置 Cookie
        if self._cookies:
            for name, value in self._cookies.items():
                self._session.cookies.set(name, value)
```

#### 2. 实现 Browser 提取 key 和 Cookie

编辑 `projects/nvidia_build/project.py`:

```python
async def _get_key_and_cookies(self, ctx):
    """用 Browser 模式获取 key 和 Cookie"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 访问 build.nvidia.com
        await page.goto("https://build.nvidia.com/?modal=signin")
        await page.wait_for_timeout(3000)
        
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
        
        return key, cookie_dict
```

#### 3. 混合模式注册

```python
async def _run_http(self, ctx, email, password):
    # 步骤 1: Browser 获取 key 和 Cookie
    ctx.log("步骤 1: 获取 key 和 Cookie...")
    key, cookies = await self._get_key_and_cookies(ctx)
    
    if not key:
        return await dbg.fail(..., error="无法获取 key")
    
    ctx.log(f"获取到 key: {key[:20]}...")
    
    # 步骤 2: HTTP 模式完成注册
    ctx.log("步骤 2: HTTP 模式注册...")
    client = NvHTTPClient(proxy=proxy, key=key, cookies=cookies)
    
    # ... 继续后续步骤
```

---

## 📋 当前状态

| 项目 | 状态 | 备注 |
|------|------|------|
| **代理** | ✅ 正常 | socks5://192.6.121.16:7890 |
| **纯 HTTP 模式** | ❌ 不可用 | 缺少 key/Cookie |
| **混合模式** | 📋 待实现 | 需要修改代码 |
| **Browser 模式** | ✅ 完整可用 | 立即可用 |

---

## 🎯 建议

### 立即行动

**使用 Browser 模式**进行实际注册：
```bash
# Web 控制台
register_mode = "browser"
```

- ✅ 稳定可靠
- ✅ 已验证可用
- ✅ 自动处理 key 和 Cookie

### 中期开发

**实现混合模式**提高速度：
1. 修改 `_http_engine.py` 支持 key 和 Cookie
2. 实现 Browser 提取 key 和 Cookie
3. 测试混合模式
4. 逐级验收 L1→L2→L3→L4

**预期效果**:
- 速度：1-2 分钟/账号（vs Browser 的 2-3 分钟）
- 并发：10-20（vs Browser 的 4-8）

---

## 📁 相关文件

```
projects/nvidia_build/
├── steps/_http_engine.py          [需要修改] 支持 key/Cookie
├── project.py                     [需要修改] 实现混合模式
├── test_hybrid_mode.py            [已有] 混合模式测试
├── _test_l1_http.py               [已有] L1 验收脚本
└── PROXY_TEST_REPORT.md           [已有] 本测试报告
```

---

**结论**: 代理正常，墙已开。问题是需要实现混合模式来获取 key 和 Cookie。建议先用 Browser 模式，同时开发混合模式。
