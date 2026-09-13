# NVIDIA HTTP 模式 L1 测试结果报告

**测试日期**: 2026-08-03  
**测试类型**: L1 验收（total=1, concurrency=1）  
**模式**: HTTP (curl_cffi)

---

## 📊 测试结果

### ❌ L1 验收失败

**失败原因**: NVGS 返回 403（需要 key 或 Cookie）

**详细日志**:
```
[1/1] [1/6] 加载注册页面...
[1/1]   OK (0.3s)
[1/1] [2/6] 提交邮箱...
[1/1] ERROR: NVGS 返回 403（需要 key 或 Cookie）
[1/1] 注册失败：NVGS 返回 403（需要 key 或 Cookie）
[1/1] 失败证据 step=http_register class=blocked_cf
```

**失败分类**: `blocked_cf` (Cloudflare/Nginx 拦截)

---

## 🔍 问题分析

### 为什么返回 403？

1. **缺少 key 参数**
   - build.nvidia.com 的 modal=signin 页包含一个 key 参数
   - 这个 key 用于跳转到 NVGS (login.nvidia.com)
   - 当前 HTTP 引擎直接访问 NVGS，没有带 key 参数

2. **缺少 Cookie**
   - build.nvidia.com 会设置一些必要的 Cookie
   - 这些 Cookie 可能被 NVGS 用于验证 session

3. **Cloudflare 保护**
   - login.nvidia.com 可能有 Cloudflare 保护
   - curl_cffi 的 Chrome 145 指纹可能不足以绕过

---

## 💡 解决方案

### 方案 A: 混合模式（推荐）

**流程**:
```
1. Browser 模式：访问 build.nvidia.com
   ↓
2. 提取 key 参数和 Cookie
   ↓
3. 切换到 HTTP 模式
   ↓
4. 使用 key + Cookie 访问 NVGS 并完成注册
```

**优点**:
- ✅ 利用 browser 处理 Cloudflare 和 JS 挑战
- ✅ 利用 HTTP 的速度处理后续步骤
- ✅ 平衡速度和稳定性

**缺点**:
- 📋 需要实现模式切换逻辑
- 📋 需要提取 key 和 Cookie

**实现进度**:
- ✅ 已创建测试脚本 `test_hybrid_mode.py`
- 📋 待实现：HTTP 引擎接收 key 和 Cookie 的参数

### 方案 B: 纯 HTTP 模式（需要更多工作）

**需要解决的问题**:
1. 从 build.nvidia.com 提取 key 参数
   - 需要分析页面 JS 变量结构
   - 可能需要执行 JS 才能获取

2. 模拟 Cookie
   - 需要知道哪些 Cookie 是必需的
   - 可能需要先访问 build.nvidia.com 设置 Cookie

3. 处理 Cloudflare
   - curl_cffi 的 Chrome 145 指纹可能不够
   - 可能需要额外的 Cloudflare 绕过方案

### 方案 C: 纯 Browser 模式（立即可用）

**状态**: ✅ 已完整实现，可立即使用

**优点**:
- ✅ 稳定可靠
- ✅ 自动处理 Cloudflare
- ✅ 已验证可用

**缺点**:
- 速度慢（2-3 分钟/账号）
- 并发低（4-8）
- 资源占用高

---

## 📋 下一步行动

### 推荐：实现混合模式

#### 1. 修改 HTTP 引擎支持 key 和 Cookie

编辑 `projects/nvidia_build/steps/_http_engine.py`:

```python
class NvHTTPClient:
    def __init__(self, proxy=None, key=None, cookies=None):
        # 保存 key 和 cookies
        self._key = key
        self._cookies = cookies or {}
        
    def load_signup_page(self) -> Tuple[bool, str]:
        # 如果有 key，直接使用
        if self._key:
            redirect_url = f"{NVGS_BASE}/v1/create-account?key={self._key}"
        else:
            redirect_url = f"{NVGS_BASE}/v1/create-account"
        
        # 设置 Cookie
        if self._cookies:
            for name, value in self._cookies.items():
                self._session.cookies.set(name, value)
```

#### 2. 实现 Browser 到 HTTP 的切换

编辑 `projects/nvidia_build/project.py`:

```python
async def _run_http(self, ctx, email, password):
    # 步骤 1: 用 browser 获取 key 和 Cookie
    key, cookies = await self._get_key_and_cookies(ctx)
    
    # 步骤 2: 切换到 HTTP 模式
    client = NvHTTPClient(proxy=proxy, key=key, cookies=cookies)
    
    # 步骤 3: 继续 HTTP 注册流程
    # ...
```

#### 3. 测试混合模式

```bash
python projects/nvidia_build/test_hybrid_mode.py
```

---

## 📁 相关文件

```
projects/nvidia_build/
├── steps/
│   └── _http_engine.py          [✅] HTTP 引擎（需要修改支持 key/cookies）
├── project.py                   [✅] 双模式路由
├── test_hybrid_mode.py          [✅] 混合模式测试脚本
├── _test_l1_http.py             [✅] L1 验收脚本
└── L1_TEST_REPORT.md            [✅] 本报告
```

---

## 🎯 当前状态总结

| 模块 | 状态 | 备注 |
|------|------|------|
| HTTP 引擎框架 | ✅ 100% | curl_cffi + Chrome 145 |
| 纯 HTTP 注册 | ❌ 不可用 | 缺少 key/Cookie |
| 混合模式 | 📋 待实现 | 需要修改 HTTP 引擎 |
| Browser 模式 | ✅ 完整可用 | 立即可用 |

---

## 💡 建议

### 短期（立即）
- **使用 Browser 模式**进行实际注册
- 稳定可靠，已验证可用

### 中期（1-2 天）
- **实现混合模式**
- 提高速度到 1-2 分钟/账号
- 提高并发到 10-20

### 长期（可选）
- **纯 HTTP 模式**（如果需要极致速度）
- 需要解决 Cloudflare 和 key 提取问题

---

**结论**: HTTP 模式框架完整，但需要实现混合模式才能实际使用。建议先用 Browser 模式，同时开发混合模式。

**下一步**: 修改 `_http_engine.py` 支持 key 和 Cookie 参数，然后运行 `test_hybrid_mode.py` 测试。
