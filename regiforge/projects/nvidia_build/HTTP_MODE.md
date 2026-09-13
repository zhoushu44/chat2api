# NVIDIA Build HTTP 注册模式说明

## 概述

nvidia_build 项目现在支持两种注册模式：

| 模式 | 底座 | 优点 | 缺点 |
|------|------|------|------|
| **browser** | Playwright（真实浏览器） | 稳定、可靠、已验证 | 较慢、资源占用高 |
| **http** | curl_cffi（协议模拟） | 快速、轻量、可高并发 | 需要调试、可能被风控 |

## 安装依赖

HTTP 模式需要安装 `curl_cffi`：

```bash
pip install curl_cffi
```

## 配置方式

在 Web 控制台中选择 `nvidia_build` 项目后，可以看到：

1. **注册模式** 选择：
   - `browser` — 有头浏览器（Playwright，稳定）
   - `http` — curl_cffi 协议（快速，需调试）

2. **共有参数**：
   - 注册密码
   - 邮箱验证码超时（秒）

3. **browser 模式专属**：
   - 浏览器底座（playwright / patchright）
   - 浏览器 Channel（chrome / edge 等）

4. **http 模式专属**：
   - 验证码解题超时（秒）

## HTTP 模式实现原理

参考 `grok_register` 的 `_lite_engine.py` 实现，nvidia_build 的 HTTP 模式流程：

```
1. Bootstrap
   └─ GET build.nvidia.com/?modal=signup

2. 提交邮箱
   └─ POST /email/submit → 进入密码页

3. 解 hCaptcha
   └─ ctx.captcha.solve(sitekey, page_url)

4. 创建账号
   └─ POST /register (密码 + hCaptcha token)

5. 邮箱 OTP
   └─ ctx.email.wait_code() → POST /otp/verify

6. 获取 API Key
   └─ 登录 → POST NGC API 创建 key
```

## 使用方式

### Web 控制台（推荐）

1. 打开 `/projects/nvidia_build`
2. 选择 `注册模式 = http`
3. 填写密码、超时等参数
4. 点「启动任务」

### API 调用

```python
POST /api/tasks
{
  "project_id": "nvidia_build",
  "params": {
    "register_mode": "http",
    "password": "your_password",
    "mail_timeout": 120,
    "captcha_timeout": 180
  },
  "total": 1,
  "concurrency": 1
}
```

### 测试脚本

```bash
# 单账号调试
python projects/nvidia_build/test_http_register.py
```

## 注意事项

### ⚠️ HTTP 模式当前状态

**HTTP 模式为示例实现，实际 URL 和字段需要根据真实页面调整：**

1. `submit_email()` 的 URL 和字段
2. `submit_password()` 的 URL 和字段  
3. `submit_otp()` 的 URL 和字段
4. hCaptcha sitekey（示例中使用的是占位值）

**建议先用 browser 模式抓包分析，再完善 HTTP 模式的 URL 和字段。**

### 调试步骤

1. **抓包分析**（browser 模式）：
   ```bash
   # 使用 browser 模式跑一次，观察网络请求
   # 或使用浏览器 DevTools 抓包
   ```

2. **提取关键信息**：
   - 注册表单的 action URL
   - 各步骤的字段名（email, password, csrf_token 等）
   - hCaptcha 的 sitekey
   - OTP 验证的 API 端点

3. **更新 `_http_engine.py`**：
   - 修改 `load_signup_page()` 的 URL
   - 修改 `submit_email()` 的 URL 和 data
   - 修改 `submit_password()` 的 URL 和 data
   - 修改 `submit_otp()` 的 URL 和 data
   - 更新 `HCAPTCHA_SITEKEY` 常量

4. **测试验证**：
   ```bash
   python projects/nvidia_build/test_http_register.py
   ```

## 与 Browser 模式对比

| 对比项 | Browser 模式 | HTTP 模式 |
|--------|-------------|----------|
| **速度** | ~2-3 分钟/账号 | ~30-60 秒/账号（理论） |
| **并发** | 4-8（建议） | 20-50（理论） |
| **资源** | 高（每个窗口~200MB） | 低（每个线程~10MB） |
| **稳定性** | 高（真实浏览器） | 中（依赖协议模拟） |
| **调试难度** | 低（可视化） | 中（需要抓包） |
| **风控风险** | 低 | 中（需注意指纹） |

## 故障排查

### HTTP 模式失败

1. **检查 curl_cffi 安装**：
   ```bash
   pip show curl_cffi
   ```

2. **检查 Provider 配置**：
   - 邮箱 Provider 是否可用
   - hCaptcha Provider 是否有余额

3. **查看任务日志**：
   - 失败步骤
   - 错误分类（blocked_cf / captcha_fail / timeout 等）

4. **使用测试脚本**：
   ```bash
   python projects/nvidia_build/test_http_register.py
   ```

### Browser 模式失败

参考 `STEPS.md` 中的调试指南。

## 下一步优化建议

1. **完善 HTTP 引擎**：
   - [ ] 分析真实注册流程的 URL 和字段
   - [ ] 更新 `_http_engine.py` 中的 API 端点
   - [ ] 测试完整的注册流程

2. **增加错误处理**：
   - [ ] 更精确的 failure_class 分类
   - [ ] 自动重试机制（针对可恢复错误）

3. **性能优化**：
   - [ ] 连接池复用
   - [ ] 并发控制（避免过高并发触发风控）

4. **文档完善**：
   - [ ] 详细的抓包教程
   - [ ] 常见问题 FAQ

## 相关文件

- `steps/_http_engine.py` — HTTP 注册引擎实现
- `project.py` — 双模式路由逻辑
- `ui/schema.json` — Web UI 配置
- `test_http_register.py` — 单账号测试脚本

## 参考实现

- `grok_register/steps/_lite_engine.py` — xAI HTTP 注册（完整实现）
- `chatgpt_register/steps/_http_engine.py` — ChatGPT HTTP 注册（Sentinel+Auth API）
