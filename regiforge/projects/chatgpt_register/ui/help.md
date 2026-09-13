# ChatGPT 注册面板说明

## 注册模式

| 模式 | 说明 | 面板额外参数 |
|------|------|--------------|
| **http（推荐）** | oumiFree 兼容：短生命周期浏览器只取 Sentinel → `curl_cffi` 调 Auth API | `http_fetch_refresh_token` |
| **browser** | 有头 Playwright 逐步点页面；遇 Cloudflare 可能需手动勾选或 Turnstile Provider | `profile_timeout` / `session_timeout` |

- 切换「注册模式」后，**无关参数自动隐藏**（schema `visible_when`，共用壳渲染）。
- 两模式共用：`mail_timeout`、`user_agent`、`browser_channel`、`browser_backend`。
- **http** 不依赖页面点「验证您是真人」；成功路径进入 `/email-verification` 后用 mailnest 收 OTP。
- **http** 依赖：系统已安装 **Google Chrome**，以及 `pip install curl_cffi`（见 `requirements.txt`）。
- authorize 出现 **403** 或卡在 authorize 时，引擎会**整段重试**（新 Sentinel + 新会话，默认最多 3 次）。
- 两种模式邮箱都走 **mailnest**（`project_code=chatgpt001`），代理走全局 `proxy/*`。

## 邮箱

- 固定 `mailnest`（迈巢临时邮箱），配置键 `email.mailnest`。
- 必填：API Key、项目编码 `chatgpt001`；可选超时自动释放。
- **不**使用 xunmail / cloudflare_worker 作为本项目邮箱（面板已限制可选 ID）。

## 验证码 / Cloudflare

- **browser**：选 `turnstile.browser_manual` 或其它 turnstile Provider；页面盾可能需人工。
- **http**：不强制页面 Turnstile；若 Sentinel 阶段被 CF 全页拦截，换代理或检查网络。

## 浏览器底座（可切换）

| 值 | 说明 |
|----|------|
| 留空 | 跟随全局 `browser.backend`（默认 `playwright`） |
| `playwright` | 原版 Playwright |
| `patchright` | CDP 泄漏修补 fork（免费，`pip install patchright`） |

- 项目字段：`projects.chatgpt_register.browser_backend`（与 NVIDIA / Grok 字段风格一致）
- **browser** 有头流程与 **http** 取 Sentinel 均生效。

## 代理

- 代理选择 `socks5`，输入 SOCKS5 链接；留空表示直连。
- 直连易触发风控时改用 SOCKS5（如 Clash `127.0.0.1:7897`）。
- **http** 引擎在 Windows 上会把 `socks5://` 转为 `socks5h://` 并使用请求级 `proxy=`，避免 TLS 失败。

## 产出

- 行格式：`email|accessToken`
- 路径：全局 `ui.keys_output_dir` — 留空为 `data/keys/chatgpt_register/api_keys.txt`；自定义为 `<文件夹>/chatgpt_register_api_keys.txt`
- http 模式可选尝试 `refresh_token`（**不**写入 keys 行，仅流程内获取）
- 左侧「最近产出」与导出区读取同一文件

## 导出 / 导入账号池（三项目共用）

控制台左侧 **导出 / 导入账号池**（与 NVIDIA、Grok 同一块 UI）：

| 目标 | 参数要点 |
|------|----------|
| `file` | 文件夹路径 + 文件名 |
| `sub2api` | **常用**：根地址、管理员令牌、模板里 `access_token: $credential` |
| `grok2api` | 可选；ChatGPT 凭据一般不走 Grok 池 |

参数写在 `export.<id>`，点「导出当前产出」走 `POST /api/export`。不迁入 oumiFree 的 Codex2API/GUI 上传。

## 项目配置键

| 键 | 说明 |
|----|------|
| `register_mode` | `http` \| `browser` |
| `http_fetch_refresh_token` | http 是否尝试 OAuth refresh_token |
| `mail_timeout` | 收码超时（秒） |
| `profile_timeout` / `session_timeout` | 仅 browser |
| `user_agent` / `browser_channel` / `browser_backend` | 浏览器与 UA |

## 不做的事

- 不迁入 oumiFree 的 IMAP/Gmail/Outlook 收码
- 不迁入其 GUI / Codex2API 上传（导出用全局 `export/*`）
- 不包含 PIX 支付
- 不把邮箱/代理/打码实现写进本项目 steps
