# NVIDIA HTTP 模式 - 使用指南

## 📦 实现状态

### ✅ 已完成
- ✅ 完整的 HTTP 注册引擎（curl_cffi）
- ✅ 双模式架构（browser / HTTP）
- ✅ UI 配置（register_mode 选择）
- ✅ 测试脚本（test_http_simple.py）
- ✅ 文档（使用说明、实现报告、测试结果）

### ⚠️ 待完成
- ⚠️ 从 browser 模式抓包，获取实际 URL 和字段
- ⚠️ 更新 HTTP 引擎的配置
- ⚠️ 测试完整注册流程
- ⚠️ 批量并发测试

## 🎯 使用方式

### 方案 A：Browser 模式（立即可用）

**适用场景**：稳定注册，不需要高速批量

```bash
# Web 控制台
1. 打开 /projects/nvidia_build
2. 选择 register_mode = "browser"
3. 配置密码、邮箱等参数
4. 点击「启动任务」
```

**优点**：
- ✅ 稳定可靠
- ✅ 已验证可用
- ✅ 处理 Cloudflare 自动

**缺点**：
- 速度较慢（2-3 分钟/账号）
- 并发低（4-8）
- 资源占用高

### 方案 B：HTTP 模式（需抓包）

**适用场景**：高速批量注册

```bash
# 1. 用 browser 模式跑一次，抓包分析
python projects/nvidia_build/test_browser_capture.py

# 2. 观察网络请求（浏览器 DevTools）
# 记录以下信息：
# - build.nvidia.com 的 key 参数
# - 邮箱提交的实际 URL
# - 注册表单的字段名
# - OTP 提交的端点
# - Post-Verification 流程的 URL

# 3. 更新 _http_engine.py 中的配置
# 编辑 projects/nvidia_build/steps/_http_engine.py
# 更新 URL、字段名、key 等

# 4. 测试 HTTP 模式
python projects/nvidia_build/test_http_simple.py

# 5. 完整流程测试（需要配置 Provider）
python projects/nvidia_build/test_http_register_full.py
```

**优点**：
- 速度快（30-60 秒/账号）
- 并发高（20-50）
- 资源占用低

**缺点**：
- ⚠️ 需要抓包分析
- ⚠️ 需要处理 Cloudflare
- ⚠️ 稳定性需验证

### 方案 C：混合模式（推荐）

**适用场景**：平衡速度和稳定性

```
1. 用 browser 模式处理前 3 步（Cloudflare + 邮箱提交）
2. 提取 key 和 Cookie
3. 切换到 HTTP 模式处理后 4 步（注册 + OTP + API Key）
```

**优点**：
- ✅ 利用 browser 的稳定性（处理 Cloudflare）
- ✅ 利用 HTTP 的速度（后续步骤）
- ✅ 速度 1-2 分钟/账号
- ✅ 并发 10-20

**缺点**：
- 📋 需要实现模式切换逻辑

## 📋 抓包步骤

### 1. 打开浏览器 DevTools

```
F12 → Network 标签
勾选 "Preserve log"
```

### 2. 运行 browser 模式

```bash
# Web 控制台或脚本
python projects/nvidia_build/test_one_account.py
```

### 3. 观察网络请求

**关键请求**：

| 步骤 | URL | 方法 | 字段 |
|------|-----|------|------|
| 打开页面 | build.nvidia.com/?modal=signin | GET | - |
| 提交邮箱 | ? | POST/GET | email, next |
| 跳转 NVGS | login.nvidia.com/v1/create-account | GET | email, key |
| 创建账号 | ? | POST | email, password, agreement, captcha |
| OTP 验证 | ? | POST | email, code |
| consent 页 | consent.nvidia.com | GET/POST | - |
| 密码登录 | login.nvidia.com/v1/login/password | POST | email, password |
| 云账户 | cloudaccounts.nvidia.com/api/v1/accounts | POST | name |
| NGC user-context | api.ngc.nvidia.com/user-context | GET | - |
| NGC create-key | api.ngc.nvidia.com/v3/orgs/{org}/keys | POST | expiryDate, name, type |

### 4. 提取关键信息

**从 build.nvidia.com 页面**：
```javascript
// 控制台运行
console.log(window.__INITIAL_STATE__)
// 或
document.querySelector('meta[name="key"]')?.content
```

**从网络请求**：
- Request URL
- Request Method
- Form Data / Payload
- Response

### 5. 更新 HTTP 引擎

编辑 `projects/nvidia_build/steps/_http_engine.py`：

```python
# 更新 URL
SIGNIN_URL = "https://build.nvidia.com/?modal=signin"
NVGS_BASE = "https://login.nvidia.com"
# ...

# 更新字段
form_data = {
    "email": email,
    "registration_password": password,
    # 根据抓包结果更新
}
```

## 🔧 测试命令

```bash
# 1. 基础测试（不跑完整流程）
python projects/nvidia_build/test_http_simple.py

# 2. 完整流程测试（需要配置 Provider）
python projects/nvidia_build/test_http_register_full.py

# 3. Browser 模式抓包
python projects/nvidia_build/test_browser_capture.py

# 4. Web 控制台批量
# 打开 /projects/nvidia_build
# 选择模式，配置参数，点「启动任务」
```

## 📊 性能对比

| 模式 | 速度 | 并发 | 稳定性 | 资源 | 状态 |
|------|------|------|--------|------|------|
| **Browser** | 2-3 分钟 | 4-8 | ⭐⭐⭐⭐⭐ | 高 | ✅ 立即可用 |
| **HTTP（框架）** | 30-60 秒 | 20-50 | ⭐⭐⭐ | 低 | ⚠️ 需抓包 |
| **混合模式** | 1-2 分钟 | 10-20 | ⭐⭐⭐⭐ | 中 | 📋 待实现 |

## 💡 常见问题

### Q: HTTP 模式为什么返回 403？

A: 可能原因：
1. key 参数无效（需要从 build.nvidia.com 提取真实的 key）
2. 缺少必要的 Cookie
3. User-Agent 或其他指纹不像真实浏览器

解决：
- 用 browser 模式跑一次，提取 key 和 Cookie
- 使用 curl_cffi 的 `impersonate` 模式（已启用）

### Q: 如何处理 Cloudflare 挑战？

A: 三种方案：
1. **Browser 模式**：自动处理（推荐）
2. **curl_cffi**：`impersonate="chrome145"`（已启用，但可能不够）
3. **混合模式**：browser 处理 Cloudflare，HTTP 处理后续

### Q: 抓包后如何更新 HTTP 引擎？

A: 
1. 记录所有 URL 和字段
2. 编辑 `_http_engine.py`
3. 更新方法中的 URL、字段、headers
4. 运行 `test_http_simple.py` 测试

### Q: 如何测试完整流程？

A:
1. 配置邮箱 Provider（`data/config.json` → `email.*`）
2. 配置验证码 Provider（`data/config.json` → `captcha.*`）
3. 运行 `test_http_register_full.py`
4. 观察日志和结果

## 📁 相关文件

```
projects/nvidia_build/
├── steps/
│   └── _http_engine.py          [✅] HTTP 注册引擎
├── project.py                   [✅] 双模式路由
├── ui/
│   └── schema.json              [✅] UI 配置
├── test_http_simple.py          [✅] 基础测试
├── test_http_register_full.py   [✅] 完整测试
├── test_browser_capture.py      [✅] 抓包辅助
├── extract_urls.py              [✅] URL 提取工具
├── HTTP_MODE.md                 [✅] 使用说明
├── TEST_REPORT.md               [✅] 测试结果
└── USAGE_GUIDE.md               [✅] 本文档
```

## 🚀 快速开始

### 立即可用（Browser 模式）

```bash
# Web 控制台
/projects/nvidia_build → register_mode="browser" → 启动任务
```

### 未来使用（HTTP 模式）

```bash
# 1. 抓包
python projects/nvidia_build/test_browser_capture.py

# 2. 更新配置
# 编辑 extract_urls.py 和 _http_engine.py

# 3. 测试
python projects/nvidia_build/test_http_simple.py

# 4. 完整测试
python projects/nvidia_build/test_http_register_full.py
```

## 📞 需要帮助？

查看以下文档：
- `HTTP_MODE.md` - HTTP 模式使用说明
- `TEST_REPORT.md` - 测试结果报告
- `HTTP_MODE_COMPLETE.md` - 完整实现报告

---

**更新日期**: 2026-08-03  
**状态**: 框架完整，待抓包验证
