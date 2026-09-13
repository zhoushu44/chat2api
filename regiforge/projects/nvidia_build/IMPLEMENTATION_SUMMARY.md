# NVIDIA Build HTTP 模式实现总结

## ✅ 已完成

### 1. 双模式架构

- ✅ `project.py` 支持 `register_mode=browser|http` 选择
- ✅ `_run_browser()` - 原有 Playwright 浏览器模式（保留）
- ✅ `_run_http()` - 新增 curl_cffi HTTP 模式（框架）
- ✅ 错误分类函数 `_classify_error()`

### 2. HTTP 引擎框架

- ✅ `steps/_http_engine.py` - HTTP 注册引擎
  - ✅ `NvHTTPClient` 类（curl_cffi 客户端）
  - ✅ `register_http()` - 异步注册入口
  - ✅ TLS 指纹模拟（Chrome 145）
  - ✅ 代理支持（socks5h://）

### 3. UI 配置

- ✅ `ui/schema.json` 新增字段：
  - ✅ `register_mode` - 模式选择（browser / http）
  - ✅ `mail_timeout` - 邮箱超时（共有）
  - ✅ `captcha_timeout` - 验证码超时（http 专属）
  - ✅ `browser_backend` / `browser_channel` - browser 专属（条件显示）

### 4. 配套文件

- ✅ `test_http_register.py` - 单账号测试脚本
- ✅ `HTTP_MODE.md` - 使用说明文档
- ✅ `IMPLEMENTATION_SUMMARY.md` - 本文件

## ⚠️ 当前状态

### HTTP 引擎为**框架示例**

当前实现的 HTTP 引擎展示了**如何从 browser 模式转换到 HTTP 模式**的完整架构，但关键的 API 端点和字段是**占位实现**，需要抓包分析后填充。

#### 为什么是框架示例？

NVIDIA 注册流程极其复杂：

1. **多域跳转**：
   ```
   build.nvidia.com 
     → login.nvidia.com (NVGS)
     → cloudaccounts.nvidia.com
     → consent.nvidia.com
     → build.nvidia.com
   ```

2. **动态表单**：
   - 邮箱提交后动态跳转到 NVGS
   - 密码页在 iframe 中
   - hCaptcha 使用 Angular 集成

3. **Post-Verification 流程**：
   - consent 页（同意开发者条款）
   - 密码登录（可能多因素认证）
   - 创建云账户（select-account）
   - 多层回调

这些复杂性使得**纯 HTTP 模式需要大量抓包分析**，不如直接用 browser 模式稳定。

## 📋 下一步：如何完善 HTTP 引擎

### 方法 1：抓包分析（推荐）

1. **用 browser 模式跑一次**：
   ```bash
   # 在 Web 控制台选择 browser 模式
   # 或设置 register_mode = "browser"
   ```

2. **观察网络请求**（浏览器 DevTools 或 Playwright 日志）：
   - 邮箱提交的 URL 和方法
   - 注册表单的字段名
   - OTP 提交的端点
   - hCaptcha 的 sitekey

3. **更新 `_http_engine.py`**：
   ```python
   # 在 submit_email() 中
   def submit_email(self, email: str):
       # 根据抓包结果填写实际 URL
       status, _, _, raw = self._session.request(
           method="POST",
           url="https://build.nvidia.com/api/auth/email",  # ← 替换为实际 URL
           data={"email": email, ...},  # ← 替换为实际字段
           headers={...},
       )
       return status == 200, ""
   
   # 同样更新 submit_registration() / submit_otp()
   ```

4. **测试**：
   ```bash
   python projects/nvidia_build/test_http_register.py
   ```

### 方法 2：混合模式（实用方案）

考虑到 NVIDIA 注册的复杂性，建议采用**混合模式**：

- **注册阶段**（步骤 1-6）：HTTP 模式
  - 提交邮箱
  - 解 hCaptcha
  - 创建账号
  - OTP 验证

- **Post-Verification 阶段**（步骤 7+）：Browser 模式
  - consent 页
  - 登录
  - 创建云账户
  - 获取 API Key

这样可以利用 HTTP 模式的速度优势（注册 + 验证码部分），同时避免复杂的 post-verification 流程模拟。

## 🔧 关键占位实现

以下方法需要抓包后更新：

| 方法 | 当前状态 | 需要填充 |
|------|---------|---------|
| `submit_email()` | 返回错误提示 | 实际 URL、字段、跳转逻辑 |
| `submit_registration()` | 返回错误提示 | NVGS create-account 的表单字段 |
| `submit_otp()` | 返回错误提示 | profile-complete 页的 OTP 提交端点 |
| `handle_post_verification()` | 建议用 browser | consent / login / select-account 全流程 |
| `HCAPTCHA_SITEKEY` | 示例值 | 实际的 hCaptcha sitekey |

## 📊 模式对比

| 特性 | Browser 模式 | HTTP 模式（框架） |
|------|-------------|-----------------|
| **实现状态** | ✅ 完整可用 | ⚠️ 框架示例 |
| **速度** | ~2-3 分钟 | ~30-60 秒（理论） |
| **并发** | 4-8 | 20-50（理论） |
| **稳定性** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐（需调试） |
| **资源占用** | 高（每个窗口~200MB） | 低（每个线程~10MB） |
| **调试难度** | 低（可视化） | 中（需要抓包） |
| **适用场景** | 稳定量产 | 快速批量（需完善） |

## 🎯 使用建议

### 当前（立即使用）

- ✅ **使用 browser 模式**：稳定可靠，已验证
- ✅ **配置**：`register_mode = "browser"`
- ✅ **并发**：4-8 个窗口

### 未来（如需高速批量）

1. **抓包分析**：用 browser 模式跑一次，记录所有网络请求
2. **填充 HTTP 引擎**：更新 `submit_*()` 方法
3. **测试验证**：用测试脚本单账号调试
4. **批量使用**：切换到 `register_mode = "http"`

## 📁 文件清单

```
projects/nvidia_build/
├── steps/
│   ├── _http_engine.py          [新增] HTTP 注册引擎（框架示例）
│   ├── _rpa.py                  [保留] Browser 模式 RPA 实现
│   ├── _flow.py                 [保留] Browser 模式流程实现
│   └── step*.py                 [保留] 各步骤实现
├── project.py                   [修改] 支持双模式路由
├── ui/
│   └── schema.json              [修改] 添加 register_mode 等字段
├── test_http_register.py        [新增] HTTP 模式测试脚本
├── HTTP_MODE.md                 [新增] HTTP 模式使用说明
└── IMPLEMENTATION_SUMMARY.md    [新增] 本文件
```

## 🔗 参考实现

- `grok_register/steps/_lite_engine.py` - xAI HTTP 注册（完整实现）
- `chatgpt_register/steps/_http_engine.py` - ChatGPT HTTP 注册（Sentinel+Auth API）

## 💡 总结

nvidia_build 项目现在支持 **browser / http 双模式**：

- **Browser 模式**：完整可用，立即可用
- **HTTP 模式**：框架示例，需抓包填充

架构已经搭好，如需完善 HTTP 模式，只需：
1. 用 browser 模式跑一次
2. 抓包分析网络请求
3. 填充 `submit_*()` 方法的 URL 和字段
4. 测试验证

**建议**：当前使用 browser 模式（稳定），如需高速批量再完善 HTTP 模式。
