# mailsys/mailnest

## 职责

提供 MailNest 临时邮箱：按注册项目解析 `project_code` 购买地址，并通过 API 轮询验证码。不同站点过滤规则不同，**不能**全站共用 `chatgpt001`。

## 包含

| 文件 | 说明 |
|---|---|
| `provider.py` | `mailnest` 邮箱 Provider：购买、收件、验证码提取与可选释放 |
| `__init__.py` | 包标识 |

## 配置

全局配置键为 `email.mailnest`：

| 字段 | 说明 |
|---|---|
| `api_key` | MailNest API Key |
| `base_url` | API 地址；默认 `https://mailnest.top` |
| `project_code` | 兜底编码（无注册项目映射时使用） |
| `poll_interval` | 收件轮询间隔（秒），默认 `3` |
| `auto_release` | 取码超时后是否尝试释放邮箱，默认 `true` |

内置默认映射（`provider.py` 硬编码，`project_code` 兜底）：

| 注册项目 | MailNest `project_code` |
|---|---|
| `chatgpt_register` | `chatgpt001` |
| `nvidia_build` | `nvidia001` |
| `grok_register` | `x-ai001` |

`task_runner` 启动任务时会注入 `registration_project_id`，Provider 据此选码。`generate_address()` 调购买接口；`wait_code()` 轮询收件并提取验证码。

### 验证码提取

支持两种验证码格式：

- **纯数字**：4–8 位数字（如 ChatGPT、NVIDIA）
- **字母数字混合**：如 xAI 的 `FPW-62T`、`RJ2-GX6` 格式

提取优先级：
1. `code_match` 字段（仅当含字母时可信）
2. 关键词附近的字母数字混合码（`code:` / `verification` 后跟 `XXX-XXX`）
3. 独立行的字母数字码
4. 纯数字回退（关键词附近 -> 任意位置）

> **注意**：MailNest 的 `code` 字段可能返回不可靠值（如 `333333`），已跳过该字段，仅从邮件正文提取。

### 旧码过滤 `skip_codes`

`wait_code(email, *, timeout, skip_codes=None)` 接受 `skip_codes`（可迭代字符串集合）。`_wait_code_sync` 内部 `skip = {str(c).strip() for c in (skip_codes or ()) if c}`，仅放行 `code not in skip` 的邮件——用于注册步骤在「验证码无效」时点「重新请求新验证码」重发后跳过上一封旧邮件再取新码。

- 调用方（如 nvidia_build step12 验证码无效重试）：将上一次用过的 code 加入 `used_codes`，传入 `cf_fetch_code(skip_codes=used_codes)` 再调一次；注入器 `sync_fetch_safe` 会透传到 `ctx.email.wait_code(skip_codes=...)`
- 未传 `skip_codes`（默认空集合）→ 不过滤，保持原有轮询行为

## 网络访问

`mailnest.top` 为国内直连服务，**默认直连**，不走任务代理：

- `TaskRunner` 启动任务时**不**向 mailnest 注入任务代理（`email.mailnest` 不接收 `email_cfg["proxy"]`），避免 socks5 代理无法访问国内服务导致超时
- 若本机网络无法直连 mailnest.top，可在配置键 `email.mailnest.proxy` 中单独指定代理地址（与任务代理解耦）
- 代理 URL 中的 `%XX` 编码会自动解码（如密码 `socks-pass%401` -> `socks-pass@1`）；带认证的 SOCKS5 会自动转换为本地 HTTP 转发器

## 相关

- [邮箱层](../README.md)
- [ChatGPT 项目](../../projects/chatgpt_register/README.md)
- [共用 Provider 表单](../../web/ui/README.md)
- [全局代理支持](../../core/README.md#全局代理支持)
