# projects/chatgpt_register

## 职责

实现 ChatGPT / OpenAI 注册。邮箱为 mailnest / cloudflare_worker；支持两种引擎：

| 模式 | 实现 | 说明 |
|------|------|------|
| `http`（推荐） | `steps/_sentinel.py` + `_http_engine.py` | oumiFree 兼容：Sentinel + curl_cffi Auth API |
| `browser` | `steps/step01..05` | 有头 Playwright 页面流程 |

成功后产出 Session Token（`accessToken`），行格式 `email|accessToken`。

## 包含

| 路径 | 说明 |
|---|---|
| `project.py` | `PROJECT` 入口，按 `register_mode` 分发 |
| `steps/_sentinel.py` | Playwright/patchright 提取 OpenAI Sentinel Token |
| `steps/_http_engine.py` | HTTP 注册引擎（邮箱/代理由 ctx 注入；403 整段重试） |
| `steps/step0N_*.py` | browser 模式编号步骤 |
| `steps/_challenge.py` / `_browser.py` | browser 辅助 |
| `ui/schema.json` | 控制台字段 / 步骤 / 约束 / 产出 |
| `ui/help.md` | 面板操作说明 |
| `HTTP_FINGERPRINT_FIX.md` | HTTP 死号修复（方案 A 指纹对齐）需求与实施记录 |

## 约定

- 邮箱为功能级全局下拉（`allowed_email_ids=[]`），实际邮件实现统一走 `ctx.email` / `email.mailnest` 等；项目 schema 不再硬编码邮箱列表。
- **禁止**在本目录复制 IMAP/Graph/打码/代理实现；一律 `ctx.email` / `ctx.proxy` / `ctx.captcha`。
- `http` 模式需要：系统 Chrome + `curl_cffi`；不加载浏览器插件。
- 代理选择 `socks5` / `http_proxy`，输入对应链接或配置动态代理池；留空表示直连。
- 控制台模式字段保留 `register_mode=http|browser`；通用 headless 选项隐藏，browser 仍固定使用有头页面。
- 不迁入 PIX；终点是 `accessToken`（可选流程内 `refresh_token`）。
- OpenAI Sentinel/HTTP 引擎**仅本项目**使用；其它项目只复用邮箱/代理/验证码/浏览器壳。
- 导出走全局 `export/*`（默认 `chatgpt2api`：`access_token` 导入），由 `ui/schema.json` 的 `import.exporter_id` 自动绑定，不在本目录写导入实现。

## 配置键

| 键 | 默认 | 说明 |
|----|------|------|
| `projects.chatgpt_register.register_mode` | `http` | `http` \| `browser` |
| `projects.chatgpt_register.http_fetch_refresh_token` | `true` | http 是否尝试 OAuth refresh_token |
| `projects.chatgpt_register.mail_timeout` | `180` | 收码超时（秒） |
| `projects.chatgpt_register.profile_timeout` | `90` | 仅 browser：资料页等待 |
| `projects.chatgpt_register.session_timeout` | `120` | 仅 browser：Session 等待 |
| `projects.chatgpt_register.user_agent` | `""` | 可选 UA |
| `projects.chatgpt_register.browser_channel` | `chrome` | 浏览器 channel |
| `projects.chatgpt_register.browser_backend` | `""` | 空=跟随全局 `browser.backend` |

## HTTP 流程（9 步）

1. Sentinel Token（短生命周期浏览器）；**取 token 后顺带访问 `chatgpt.com/api/auth/csrf` 预热**：让真 Chrome 通过 Cloudflare 挑战，取得 `chatgpt.com` 的 `__cf_bm`/`cf_clearance`，供后续 curl_cffi 复用（同 UA + 同代理出口 IP）。curl_cffi 本身过不了 CF 的 JS 挑战，必须靠浏览器拿放行 cookie。
2. CSRF（`chatgpt.com/api/auth/csrf`，复用上一步 CF cookie；无 cookie 会被 CF `cf-mitigated: challenge` 403）
3. 发起注册（signin/openai）
4. OAuth 跳转（成功应到 `/email-verification`；403 则整段重试）
5. 邮箱 OTP（`ctx.email.wait_code`）
6. 验证 OTP
7. create_account（带 sentinel header）
8. 建立会话 + 可选 OAuth PKCE refresh_token
9. 产出 `accessToken`

### HTTP 指纹（方案 A → A+）

针对 HTTP 注册"跑通但死号"问题，注册请求已做指纹对齐 + 随机化，详见 [HTTP_FINGERPRINT_FIX.md](HTTP_FINGERPRINT_FIX.md)：

- **对齐（A）**：`impersonate` 按 UA 版本动态映射；统一 `_browser_headers` 带 `sec-ch-ua*` / `sec-fetch-*`（API `cors/empty`、表单/OAuth `navigate/document`）；Sentinel 提取后 1~3s 人类时序
- **随机化 + 地理联动（A+）**：`_fingerprint.py` 每次注册随机一套（chrome/firefox/safari 家族，UA/TLS/CH/语言/时区/屏幕/硬件全绑定）；按代理出口国家（`detect_country` 探测）选语言时区；curl 与 Sentinel 浏览器共用同一套
- **边界**：token 由浏览器生成、请求由 curl 发送的上下文断裂未根治，仍死号切方案 B（QuickJS 跑真 sdk.js）

## 控制台产出

Token 使用全局 `ui.keys_output_dir`：留空写入 `data/keys/chatgpt_register/api_keys.txt`。行格式 `email|accessToken`。

独立入口：`/projects/chatgpt_register`。

## 成熟度验收

ChatGPT 的 `http`（Sentinel + Auth API）或 `browser`（有头页面）都可作为 L4 主路径。L4 必须从 `/projects/chatgpt_register` 的 Web 控制台点击 `#btnStart` 启动，并满足 L3 同级并发与成功率门禁；仅用 API、脚本或一次成功不能认证 L4。默认门禁为：L1 单账号 1×1；L2 同配置单并发至少 5 个且成功率 ≥80%；L3 提高并发后成功率相对 L2 跌幅不超过 15 个百分点。任一级失败先查看 `data/debug/chatgpt_register/` 证据并修复，同级通过后再升级。

### L4 验收记录（2026-08-20）

http 主路径 + Web 控制台批量并发验收通过：
- concurrency=2：10/10 (100%)，task_id `e367512d0885`
- concurrency=5：10/10 (100%)，含 2 次 OTP 409 代理重新获取后重试成功
- wary 代理池：forwarder 端口生命周期完整，无泄漏无冲突；per-account state 在并发和重试路径上均无互相覆盖
- add-phone 拦截：全部 20 账号 refresh_token 均命中 `/add-phone`，accessToken 不受影响（详见 [REGISTRATION_FLOW.md §15](REGISTRATION_FLOW.md)）

## 相关

- [项目层](../README.md)
- [成熟度门禁](../../.trae/skills/project-maturity-gate/SKILL.md)
- [步骤说明](steps/README.md)
- [UI 规划](ui/README.md)
- [MailNest 邮箱](../../mailsys/mailnest/README.md)
- 参考实现思路：[oumiFree](https://github.com/zbqoumi/oumiFree)（仅 Sentinel+API 流程，未整仓迁入）
