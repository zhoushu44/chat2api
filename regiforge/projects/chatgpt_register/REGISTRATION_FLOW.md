# ChatGPT 注册流程详解（chatgpt_register 全量文档）

> 本文是 `projects/chatgpt_register` 的**一站式详细文档**：模式、参数、逐步流程、端点、指纹、重试、失败排查、产出落盘、号池保活、实测数据、已知限制，全部覆盖。
> 事实来源：代码（`project.py` + `steps/*`）与 2026-08-14 实测（`data/keys/chatgpt_register/egress.jsonl` 等）。代码变更后以代码为准。

---

## 目录

1. [项目概览](#1-项目概览)
2. [目录结构](#2-目录结构)
3. [环境依赖](#3-环境依赖)
4. [全部配置参数](#4-全部配置参数)
5. [依赖的 Provider](#5-依赖的-provider)
6. [HTTP 模式完整流程（推荐）](#6-http-模式完整流程推荐)
7. [防检测三件套：指纹 / Sentinel / QuickJS PoW](#7-防检测三件套指纹--sentinel--quickjs-pow)
8. [重试与容错机制](#8-重试与容错机制)
9. [browser 模式完整流程](#9-browser-模式完整流程)
10. [2FA 两种绑定方式](#10-2fa-两种绑定方式)
11. [失败分类与排查手册](#11-失败分类与排查手册)
12. [产出与落盘文件](#12-产出与落盘文件)
13. [号池导入与保活链](#13-号池导入与保活链)
14. [实测数据（2026-08-14）](#14-实测数据2026-08-14)
15. [已知限制与待办](#15-已知限制与待办)
16. [成熟度验收](#16-成熟度验收)

---

## 1. 项目概览

| 项 | 值 |
|---|---|
| project_id | `chatgpt_register` |
| 项目名 | ChatGPT / OpenAI |
| 注册模式 | `http`（Sentinel + curl_cffi Auth API，推荐） \| `browser`（有头 Playwright 页面流程） |
| 邮箱 | 固定 `mailnest`（迈巢临时邮箱，project_code=`chatgpt001`）；可选 `cloudflare_worker` |
| 代理 | `socks5` / `http_proxy`（全局 Provider，留空=直连） |
| 验证码 | Turnstile 类型（`browser_manual` / `capsolver` / `captcharun` / `yescaptcha`）；http 模式不强制 |
| 产出 | Session Token（`accessToken`），行格式 `email\|accessToken` |
| 独立入口 | `http://127.0.0.1:8787/projects/chatgpt_register` |

**双模式选型**：

- `http`：oumiFree 兼容协议流。短生命周期浏览器只取 Sentinel Token + CF cookie，其余全部走 `curl_cffi` 调 Auth API。不点页面盾，速度快（单账号 94~120s），批量首选。
- `browser`：有头 Playwright 逐步点页面。可能需人工过 Cloudflare/Turnstile，速度慢但环境最真实。

**能力来源**：流程改编自 oumiFree；存活率五能力（密码注册、QuickJS PoW、TLS 瞬断重试、OTP 补发、2FA 绑定）吸收自 `gpt-outlook-register v0.5.5`（2026-08-14 吸收完成）。

---

## 2. 目录结构

```text
projects/chatgpt_register/
├── project.py                    # PROJECT 入口：按 register_mode 分发 + refresh_token 落盘
├── steps/
│   ├── _fingerprint.py           # A+ 随机指纹 + IP 地理联动（chrome/firefox/safari 家族）
│   ├── _sentinel.py              # 短生命周期浏览器提取 Sentinel Token + CF cookie 预热
│   ├── _sentinel_quickjs.py      # Node 子进程跑真实 sdk.js 按 flow 现算 Sentinel（PoW）
│   ├── _openai_sentinel_quickjs.js  # QuickJS wrapper（stdin/stdout JSON 协议）
│   ├── _http_engine.py           # HTTP 注册引擎（9 步主流程 + 密码注册 + OTP + 2FA + RT）
│   ├── step01_open_login.py      # browser：打开登录页
│   ├── step02_submit_email.py    # browser：提交邮箱（防误点第三方登录）
│   ├── step03_verify_email.py    # browser：收 OTP 并填写（含 API 兜底提交）
│   ├── step04_complete_profile.py# browser：填姓名/生日（含 create_account API 兜底）
│   ├── step05_extract_session.py # browser：读 /api/auth/session 取 accessToken
│   ├── step06_setup_2fa.py       # browser：页面式 TOTP 2FA（可选）
│   ├── _browser.py               # click_by_text / fill_first / submit_near 等页面辅助
│   └── _challenge.py             # Cloudflare/Turnstile 检测、注入、自动/人工过盾
├── ui/
│   ├── schema.json               # 控制台字段/步骤/约束/产出/导入绑定
│   └── help.md                   # 面板操作说明
├── README.md                     # 项目层说明
├── HTTP_FINGERPRINT_FIX.md       # HTTP 指纹方案（A→A+）与死号修复记录
├── 2FA_SETUP.md                  # 2FA 说明
└── REGISTRATION_FLOW.md          # 本文
```

---

## 3. 环境依赖

| 依赖 | 用途 | 说明 |
|---|---|---|
| **Google Chrome（系统安装）** | http 模式 Sentinel 提取 | `_system_chrome_path()` 找不到时 http 模式直接报错；patchright 底座可用 `channel=chrome` |
| **curl_cffi** | http 模式全部 API 请求 | TLS 指纹模拟（impersonate）；缺失时报 `pip install curl_cffi` |
| **Node.js** | QuickJS PoW（`http_sentinel_refresh=true`） | `node` 在 PATH，或 `OPENAI_SENTINEL_NODE_PATH` 环境变量 |
| **Playwright / patchright** | Sentinel 浏览器 + browser 模式 | patchright 可选（`pip install patchright`） |
| **mailnest API Key** | 临时邮箱 | 配置键 `email.mailnest`（.env / data/config.json） |
| **SOCKS5 代理** | 出口 IP | 直连（中国大陆）必被墙；代理建议住宅 IP |

Windows 注意：curl_cffi 的 `socks5://` 常报 `curl: (35) TLS connect error`，引擎自动转换为 `socks5h://`（远程 DNS）。

---

## 4. 全部配置参数

### 4.1 项目参数（`projects.chatgpt_register.*`）

| 键 | 类型 | 默认 | 生效模式 | 说明 |
|---|---|---|---|---|
| `register_mode` | select | `http` | 全部 | `http` \| `browser` |
| （强制）设密码 | — | **强制** | http | 注册链先 POST user/register 设密码再 OTP（**不可关闭**：无密码号只能靠临时邮箱收码登录，域名失效即永久丢失）。失败 → `fail_http_no_password` |
| `http_sentinel_refresh` | checkbox | `true` | http | QuickJS 按 flow 现算 Sentinel（`username_password_create` / `oauth_create_account`），flow 不匹配是风控特征；需要 Node |
| `http_fetch_refresh_token` | checkbox | `true` | http | 注册后走 Codex OAuth 尝试换 refresh_token（详见 §15 已知限制：目前普遍被 add-phone 拦截） |
| （强制）绑 2FA | — | **强制** | http | 注册成功后程序化绑定 TOTP 2FA（**不可关闭**，secret 只出现一次）。失败 → `fail_http_no_2fa` |
| `mail_timeout` | number | `180`（30~600） | 全部 | 收邮箱 OTP 超时秒数 |
| `user_agent` | text | `""` | 全部 | 显式 UA；留空则每次注册随机 A+ 指纹 |
| `browser_channel` | text | `chrome` | 全部 | 浏览器 channel |
| `browser_backend` | select | `""` | 全部 | 空=跟随全局 `browser.backend`；`playwright` / `patchright`。http 取 Sentinel 也生效 |
| `profile_timeout` | number | `90`（15~300） | browser | 资料页等待 |
| `session_timeout` | number | `120`（30~600） | browser | Session 等待 |
| `enable_2fa` | checkbox | `false` | browser | 页面式 2FA（step06） |
| `2fa_timeout` | number | `120`（60~300） | browser | 2FA 等待（仅 `enable_2fa=true` 时显示） |

模式联动：schema 用 `visible_when` 声明显隐（如 `profile_timeout` 仅 `register_mode=browser` 显示），由共用壳 `applyProjectFieldVisibility` 处理；隐藏只改 UI 不删已存值。

### 4.2 当前生产配置（data/config.json 实况）

```json
"chatgpt_register": {
  "register_mode": "http",
  "http_fetch_refresh_token": true,
  "mail_timeout": 180,
  "http_sentinel_refresh": true
}
```

任务参数（`ui.project_state.chatgpt_register`）：`captcha_id=turnstile.browser_manual`、`email_id=mailnest`、`proxy_id=socks5`、`total/concurrency/stagger` 按批次调整。

### 4.3 Provider 配置键

| Provider | 配置键 | 当前值（脱敏） |
|---|---|---|
| mailnest | `email.mailnest` | API Key + project_code=`chatgpt001`，`auto_release=true`，`poll_interval=3` |
| wary | `proxy.wary` | WarpGate 代理池地址 + 管理令牌，`pool_size=20`，`sticky_minutes=10` |
| socks5 | `proxy.socks5` | 固定出口 `socks5://***@192.6.121.16:7890`（每次 api 提取换 IP 时走粘性 10min） |
| chatgpt2api | `export.chatgpt2api` | 号池地址 + 管理令牌（导入用） |

---

## 5. 依赖的 Provider

| 能力 | Provider ID | 在流程中的角色 |
|---|---|---|
| 邮箱 | `mailnest` | `ctx.email.generate_address()` 开号 → OTP 阶段 `ctx.email.wait_code(addr, timeout, skip_codes=…)`；`skip_codes` 用于密码注册切流程后过滤旧码（单次长轮询，不能拆短轮询否则 provider 超时自动 release） |
| 代理 | `wary` / `socks5` / `http_proxy` | `ctx.proxy.acquire()`；http 模式取 `meta.upstream` 作为 curl 代理；Sentinel 浏览器走同一出口。wary 为 WarpGate 代理池（每账号独立本地 forwarder，释放时 stop forwarder） |
| 验证码 | `turnstile.*` | browser 模式页面盾；http 模式不强制（Sentinel 阶段被 CF 全页拦截时才需处理） |
| 导出 | `chatgpt2api` | 控制台「导入账号池」按钮（`ui/schema.json` 的 `import.exporter_id` 自动绑定） |

项目内**禁止**出现邮箱/代理/打码实现，一律 `ctx.email` / `ctx.proxy` / `ctx.captcha`。

---

## 6. HTTP 模式完整流程（推荐）

入口：`project.py::_run_http` → `steps/_http_engine.py::register_http` → `_register_sync`（工作线程内同步执行）。

```text
生成邮箱 ──► [0] 探测出口国家/时区（ip-api）──► [1] 随机指纹（A+）
        ──► [2] CSRF ──► [3] 发起注册 signin ──► [4] OAuth 跳转（手动跟跳）
        ──► [5] 密码注册 + OTP（先设密码→主动重发→跳旧码等新码→validate，401 补发重试）
        ──► [7] create_account（flow 现算 sentinel）──► [8] 建会话读 accessToken
        ──► [8.5] Codex OAuth 换 refresh_token（可选）──► [8.6] 绑定 TOTP 2FA（可选）
        ──► [9] 完成，返回全部凭证
```

### [0] 出口探测（`detect_country`）

- `GET http://ip-api.com/json/?fields=status,countryCode,timezone`（走**同一代理出口**，curl impersonate=chrome131，超时 8s）
- 得到 `(country, ip_tz)`，喂给指纹地理联动；失败回退 `("US", "")`
- 同时写入出口观测日志（见 §12）

### [1] 随机指纹（A+，每次注册一套）

详见 §7.1。取完 Sentinel 后到 curl 发首请求之间 `sleep(random 1~3s)` 模拟人类时序。

### [2] CSRF

```text
GET https://chatgpt.com/api/auth/csrf
```

- 复用 Sentinel 浏览器预热拿到的 CF cookie（`__cf_bm` / `cf_clearance`）；无 cookie 会被 CF `cf-mitigated: challenge` 403
- 解析优先级：JSON `csrfToken` > Set-Cookie `__Host-next-auth.csrf-token`（取 `%7C` 前段）；**禁止**回退成 `'true'`（会被 signin 打回）
- 超时 45s；失败 → `RetriableRegisterError`（整段重试）

### [3] 发起注册（signin）

```text
POST https://chatgpt.com/api/auth/signin/openai
  ?prompt=login&ext-oai-did=<oai-did>&auth_session_logging_id=<uuid32>
  &screen_hint=login_or_signup&login_hint=<email>
body: csrfToken=<csrf>   (x-www-form-urlencoded)
```

- 表单提交语义头：`sec-fetch-mode: navigate` / `sec-fetch-dest: document`
- 成功：JSON `{"url": <authorize URL>}` 或 302 Location
- `csrf=true` 或落回 `/api/auth/signin` → CSRF 无效，整段重试

### [4] OAuth 跳转（手动跟跳，最多 12 hop）

- 首跳 authorize 75s 超时，后续 45s；`allow_redirects=False` 逐跳跟
- 请求带 `openai-sentinel-token` / `openai-sentinel-so-token` 头 + 多域 cookie（2026-07 起必需，否则 403 CF）
- 跨站导航头：`sec-fetch-site: cross-site`、`upgrade-insecure-requests: 1`
- **成功判定**：落地 URL 含 `email-verification` / `email-otp` / `about-you` / `create-account`（302 Location 已触发服务端发 OTP）
- **失败判定**（→ 整段重试）：
  - status ≥ 400
  - 卡在 `/api/accounts/authorize` 且未到验证页
  - body 含 `just a moment` / `cf-ray`（CF 拦截）
  - 回落 `chatgpt.com/auth/login`（未发 OTP）
  - `/log-in` 且无 signup → `RuntimeError("账号可能已存在")`（**不重试**，换邮箱）

### [5] 邮箱 OTP（含密码注册，注册收口强制项）

设密码为**强制不变式**（无配置开关，失败即 `fail_http_no_password`，不再降级为无密码 OTP 路径）的完整子流程：

1. 先收第一封 OTP（`wait_code`，若邮件没自动发也不死路）
2. **密码注册** `_register_password`：
   - 先 `GET /create-account/password` 建立服务端状态（v0.5.5 HAR 确认必需）
   - QuickJS 按 `flow=username_password_create` 现算新 sentinel（flow 必须匹配）
   - `POST https://auth.openai.com/api/accounts/user/register`，body `{"password": <10位随机+!A1>, "username": <email>}`
   - 200 = OpenAI 侧账号+密码已建好；服务端切流程 `email_otp_send`，**旧 OTP 立即失效**
3. **主动重发 OTP** `_send_otp`：`GET /api/accounts/email-otp/send`（用刷新后的 token）；失败再 `_resend_otp`（POST `/email-otp/resend`）
4. **等新码** `_wait_new_code`：透传 `skip_codes={旧码}` 给 mailnest，**单次长轮询**（mail_timeout 内过滤旧邮件；拆短轮询会导致 provider 超时自动 release 邮箱）
5. **验证 OTP**：`POST /api/accounts/email-otp/validate`，body `{"code": <code>}`，带 sentinel 头（2026-07 起无头必 403）
   - **401 错码** → `resend` 补发一次 → `_wait_new_code(skip={旧码})` → 再 validate（v0.5.5 重试）
   - 非 200 → 失败
6. 设密码失败 → **不降级**，直接 `RuntimeError`（注册收口要求，不产出无密码账号）

### [7] 创建账号

- `sentinel_refresh=true` 时先 QuickJS 按 `flow=oauth_create_account` 现算 sentinel
- `POST https://auth.openai.com/api/accounts/create_account`，body `{"name": <随机姓名>, "birthdate": <1985-2004 随机>}`，带 sentinel 头
- 403 `unsupported_country_region_territory`（出口 IP 被风控）→ 整段重试
- 200 返回 `continue_url`

### [8] 建立会话

- 手动跟 `continue_url` 跳转（≤8 hop，导航语义头）
- `GET https://chatgpt.com/api/auth/session`（重试 3 次）→ `accessToken` / `sessionToken`

### [8.5] OAuth 换 refresh_token（可选，`http_fetch_refresh_token=true`）

Codex 授权码流（对齐 v0.5.5），**注意不带 `screen_hint`/`max_age=0`**（会强制重新认证被打回登录页）：

```text
client_id   = app_EMoamEEZ73f0CkXaXp7hrann   (Codex CLI)
redirect_uri= http://localhost:1455/auth/callback
scope       = openid email profile offline_access
            + id_token_add_organizations=true + codex_cli_simplified_flow=true + prompt=login
PKCE S256（code_verifier=token_urlsafe(64)）
```

手动跟跳（≤20 hop，`allow_redirects=False`）捕获 callback 的 `code`，处理三类 200 中间页：

| 中间页 | 处理 |
|---|---|
| `/choose-an-account` | 正则抓 `us_[A-Za-z0-9]{16,}` → `POST /api/accounts/session/select`（JSON）→ 取 `continue_url`；200/400（TLS 双发重复 select，cookie 已 set）都重走 authorize |
| `/add-phone` | 去 `prompt` 参数刷新重试（≤2 轮，间隔 1.2s）；耗尽则放弃 RT（**当前普遍卡在这里，见 §15**） |
| 其它 200 | 未实现交互，放弃 |

拿到 code 后 `POST /oauth/token`（form：grant_type=authorization_code / client_id / code / redirect_uri / code_verifier）→ `refresh_token`。成功时返回的 `access_token` 会覆盖 [8] 的。

### [8.6] 绑定 TOTP 2FA（注册收口强制项）

强路径（注册会话"最近认证过"，enroll 不会 401 recent_auth_required，v0.5.5 实测 6.2s、零 PoW、零邮件）：

1. `GET chatgpt.com/backend-api/accounts/mfa_info`（幂等：已绑则跳过，但拿不到 secret → 视为失败）
2. `POST /backend-api/accounts/mfa/enroll`，body `{"factor_type": "totp"}` → **secret 只在本次响应出现**
3. 本地 `_totp_now(secret)`（RFC 6238，30s 窗口 6 位码）
4. `POST /backend-api/accounts/mfa/user/activate_enrollment`，body `{code, factor_type, session_id}`（429 可等 60s 换码重试）

**强制不变式**：未拿到 `mfa_enabled=true` + 非空 `totp_secret` → `RuntimeError`，注册失败（`fail_http_no_2fa`），不产出。

### [8.7] 立即验活（注册收口强制项）

- `GET https://chatgpt.com/backend-api/me`（Bearer access_token，复用同一 session/代理/指纹），2xx 为通过
- 非 2xx 或请求异常 → `RuntimeError`，注册失败（`fail_http_not_alive`），挡掉「刚签发就失效」的脏号

### [9] 完成

返回 dict：`email / password(设密成功时) / name / birthdate / access_token / session_token / refresh_token / totp_secret / mfa_enabled / plan_type`（`plan_type` 从 accessToken JWT 的 `chatgpt_plan_type` 解码，free/plus/pro/team）。

`project.py` 侧：
- 无 token → `fail_http_no_token`
- **注册收口校验**：无 password → `fail_http_no_password`；无 `mfa_enabled`/`totp_secret` → `fail_http_no_2fa`；验活未过已在 [8.7] 拦截 → 均**不写入产出、不导入号池**
- 有 refresh_token → `_save_refresh_token` 追加写 `data/keys/chatgpt_register/refresh_tokens.jsonl`（`email|rt`，O_APPEND 原子写）
- extra 带齐 `mode/type/source_type/plan_type/egress_*` + `has_password=true / mfa_enabled=true / totp_secret / alive_verified=true`

---

## 7. 防检测三件套：指纹 / Sentinel / QuickJS PoW

### 7.1 A+ 随机指纹（`_fingerprint.py`）

**背景**：同指纹批量注册是 OpenAI 反欺诈最大关联信号（开源实测同指纹批量存活率 ~2%）。

每次注册随机一套**内部一致**的画像，curl 与 Sentinel 浏览器共用：

| 维度 | 取值 |
|---|---|
| 家族（权重） | chrome 55% / firefox 25% / safari 20% |
| chrome 版本 | 131 / 136 / 142 / 145（curl_cffi 0.15.0 确认可构造） |
| UA | Windows Chrome / Firefox / macOS Safari，版本与 impersonate 严格一致 |
| TLS | `impersonate` 精确版本（chrome131 等） |
| Client Hints | chrome 家族全套 `sec-ch-ua*`（含 full_version_list/arch/bitness/model/platform_version/wow64，GREASE 按版本取值）；firefox/safari 不发（真实行为） |
| 语言 | 按出口国家表选（`US→en-US,en,es-US`…），q 值顺序打乱防模板化 |
| 时区 | 按国家加权（US: NY 40%/LA 30%/Chicago 20%/Denver 10%）；未知国家用 ip-api 实测时区兜底 |
| 屏幕/视口 | Windows 5 档 / Mac 4 档；viewport = 高度-40 |
| 硬件 | 家族绑定：chrome `Win32`+`Google Inc.`+hc(4-16)+mem(4/8)；safari `MacIntel`+`Apple Computer, Inc.`+dpr 2.0 |
| 地理联动 | 语言/时区必须匹配出口 IP 国家（国家级风控信号） |

显式配置 `user_agent` 时走 `fingerprint_from_user_ua`：不随机 UA，其余仍随机（版本映射对齐 `impersonate_for_ua`）。

### 7.2 Sentinel 提取（`_sentinel.py`）

短生命周期浏览器（headless，真 Chrome 或 patchright）：

1. 构造 authorize URL：client_id=`app_X8zY6vW2pQ9tR3dE7nK1jL5gH`（ChatGPT web）、`prompt=login&screen_hint=signup`、device_id=uuid4
2. context 画像全取指纹（UA/locale/timezone/viewport + `add_init_script` 注入 navigator 硬件：hardwareConcurrency/deviceMemory/maxTouchPoints/platform/vendor/devicePixelRatio）
3. 打开页面等 `window.SentinelSDK`；**CSP strict-dynamic 兜底**：页面 script 不执行时，经代理下载 `sentinel.openai.com/backend-api/sentinel/sdk.js` → 解析 versioned URL → eval 注入
4. `SentinelSDK.init()` → `token()`（Promise.race 20~25s 防挂起）取主 token；再取 so-token（可失败）
5. **CF 预热**：访问 `chatgpt.com/api/auth/csrf` 让真 Chrome 过 CF 挑战，取 `__cf_bm`/`cf_clearance`（2026-08 起 curl 直连该 API 会 `cf-mitigated: challenge` 403，必须浏览器拿）
6. 返回 `{sentinel_token, sentinel_so_token, cookie_str, oai_did}`

cookie 由 `_apply_sentinel_cookies` 挂到 `.openai.com/.auth.openai.com/auth.openai.com/.chatgpt.com/chatgpt.com` 五域（skip `oai-login-csrf/oai-did/oai-client-auth/auth-session`），`oai-did` 显式补设（authorize 风控更认）。

### 7.3 QuickJS PoW（`_sentinel_quickjs.py`）

**为什么**：纯 Python 合成 PoW 能过 `/sentinel/req` 表面校验（200），但 OTP 派发服务会用真 sdk.js 服务端深校验 token → 合成的过不去 → **邮件 silent-drop**（收不到码）。必须 Node 跑真 sdk.js 输出同款 token。

流程（`get_sentinel_token_via_quickjs`）：

1. 下载真实 `sdk.js`（`https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js`）到 `%TEMP%/openai-sentinel-demo/<ver>/` 缓存（每版本一次）
2. `node _openai_sentinel_quickjs.js`，action=`requirements`（喂 navigator 指纹：UA/屏幕/语言/platform/vendor/hw_concurrency/dpr/时区，与 A+ 指纹一致）→ 得 `request_p`
3. `POST /backend-api/sentinel/req`（body `{p, id, flow}`）拿 challenge
4. action=`solve`（request_p + challenge + flow + behavior_duration_ms=4200）→ `(token, so_token)`
5. **SO token 是否必需由服务端 challenge 决定**（`so.required`；`username_password_create` 无 so 块）；服务端要求但求解为空 → 中止返回 None（防封号）
6. 网络类异常（TLS 瞬断）原样上抛由 `_TlsRetrySession` 兜住；JS/PoW 失败返回 None（沿用旧 token，不阻断）

调用点：密码注册前（flow=`username_password_create`）与 create_account 前（flow=`oauth_create_account`）。

---

## 8. 重试与容错机制

### 8.1 TLS 瞬断重试（`_TlsRetrySession`，吸收 v0.5.5）

- 代理链路偶发 `curl: (35) TLS connect error / OPENSSL_internal`（v0.5.5 实测 5.4%，链路级瞬断，与指纹无关）
- **必须原 session 重试**（session 装 oai-did/csrf，重建直接 409 invalid_state）
- 实现：包装 Session 的 get/post；仅兜 TLS 标记（`curl: (35)` / `tls connect error` / `openssl_internal` / `sslerror`）；超时/HTTP 错误/业务异常原样抛（别把服务端拒绝也重试，反而像异常流量）；2 次退避 1.5s×n；实测原 session 重试 8/8 一次恢复

### 8.2 整段重试（`register_http`，默认 max_attempts=3）

触发条件（`RetriableRegisterError` 或 RuntimeError 命中 retriable markers）：

- Sentinel 提取失败 / token 空
- CSRF 失败/超时
- 注册发起失败 / CSRF 无效被打回
- OAuth hop 超时或请求失败 / 未进入验证页 / CF 拦截
- 创建账号 403（`unsupported_country_region_territory`）/ 409 / 429
- OTP 验证 403 / 409
- `curl: (28)` 超时等网络错误

重试动作：**新 Sentinel + 新会话 + 新指纹**（防关联），间隔 `min(8, 2×attempt)` 秒。

**不重试**（邮箱已消耗/无意义）：OTP 收码超时、`账号可能已存在`。

每次尝试（含 retry/fail）都写 `egress.jsonl`（§12），重试耗尽 → `HTTP 注册失败（已重试 N 次）`。

---

## 9. browser 模式完整流程

入口：`project.py::_run_browser` → `browser_session`（有头单窗口）→ `RegisterDebug.run_step` 逐步包（trace retain-on-failure，成功丢弃）。

步骤链（失败即返回 `dbg.fail`，证据落 `data/debug/chatgpt_register/<task>/<idx>/`）：

### step01_open_login

- 直跳 `https://auth.openai.com/authorize?email=<email>`（带邮箱参数），3 次尝试
- 失败兜底：`chatgpt.com/auth/login` → `_click_email_login_entry`（只点邮箱入口，**排除 google/apple/microsoft/facebook/github/sso 第三方按钮**）
- 成功条件：邮箱输入框 visible（`#email, input[type=email], input[name=email], input[autocomplete=email], placeholder 匹配`）
- 页面被关 → 明确报错"请保持自动打开的 Chrome 窗口"

### step02_submit_email

- 先处理 Cloudflare（`wait_cloudflare_if_needed`，见下）
- 等邮箱框 → fill + dispatch input/change + **React 原生 setter**（`HTMLInputElement.prototype.value` descriptor）确保 React 感知
- `_email_is_confirmed` 确认框内值=本轮邮箱，否则停止提交（防误点其它登录）
- 提交策略（最多 20 轮，每 0.5s）：
  1. `_click_email_form_submit`：只点邮箱框所在 form 的 submit/继续按钮（排除第三方）
  2. 兜底点 `Continue/继续/Next`
  3. 邮箱被清空 → 重填 + Enter
  4. 邮箱框 Enter
  5. 第 8 轮仍卡 → 重开带邮箱的授权入口（`_recovery_attempt` 最多 2 层递归）
- 异常恢复：chrome-error 页（代理掉线）→ 重新导航；会话过期（"会话已结束"）→ 重新导航；误跳第三方登录页 → 导航回授权入口
- 成功条件：`_still_on_email_gate` 为假（URL 含 password/email-verification/otp/create-account/about-you/callback 等）或 DOM 判定已离开（`_page_looks_post_email`：出现 OTP/密码框或 CF 挑战）

### step03_verify_email

- 先 `wait_cloudflare_if_needed`
- `_resubmit_email_if_needed`：step02 误判兜底，三招重提交（点继续按钮 → Enter → **浏览器内直接调 `chatgpt.com/api/auth/signin/openai` API** 并跟 302）
- `_wait_code_input`：等 OTP 输入框（name=code / autocomplete=one-time-code / inputmode=numeric 等）；URL 已到 password/create-account 则跳过；超 30s 刷新页面重触发一次；会话过期 3 次报错
- `ctx.email.wait_code(email, timeout)` 收码（mailnest）
- `_fill_code`：优先逐格 fill（maxlength=1 的多框）；兜底 aggregate 框 React setter；最后兜底填所有可见框
- 提交（≤30 轮）：点 Continue → Enter → `form.requestSubmit` → 点第一个可见按钮 → **第 3/8/15 轮直接 `POST auth.openai.com/api/accounts/email-otp/validate`**（浏览器内 fetch）并跟 `continue_url`
- 成功条件：URL 离开 verification

### step04_complete_profile

- 随机 `姓名（First Last）+ 生日（1985-2004）`
- 已在主站（chatgpt.com 且无 auth/login/signup/authorize）→ 跳过
- 引导页先点 `跳过/skip/get started/ok`
- `_fill_profile_once`：按 label 智能识别 first/last/full name 与生日框（支持 MM DD YYYY / DD MM YYYY 等格式化），排除 email/password/phone 等无关框
- 提交：UI（requestSubmit → click_by_text → 原生按钮）
- UI 卡 about-you → `_create_account_api`：浏览器内直接 `POST auth.openai.com/api/accounts/create_account`（对齐 oumiFree）→ 跟 `continue_url` 回主站

### step05_extract_session

- 关闭 onboarding 弹窗（click_by_text + 全量扫 accept/ok/continue 按钮）
- 仍在 about-you/email-verification → 等待；不在 chatgpt.com → 导航 `https://chatgpt.com/`
- `_read_session`：页面内 `fetch('/api/auth/session')` → `accessToken`（优先）→ `sessionToken`
- 备用：localStorage（eyJ 开头/JSON 含 token 字段）→ cookie（session-token 类）
- 超时（默认 120s）→ `等待 Session Token 超时`

### step06_setup_2fa（可选，`enable_2fa=true`）

页面式（较旧，推荐用 http 模式的程序化绑定代替）：设置页 → 找 2FA 区（双重验证/Two-factor/TOTP）→ 提取 secret（二维码 otpauth:// / 文本 XXXX-XXXX 格式 / 只读输入框）→ 存备用码 → 等待验证完成（需实时 TOTP 码）。

### Cloudflare 处理（`_challenge.py`，贯穿各步）

`wait_cloudflare_if_needed(page, ctx, timeout, captcha)`：

1. 检测：URL 含 `challenges.cloudflare.com` / DOM 有 turnstile 挂件 / 文案「请稍候/just a moment/verify you are human」
2. 自动尝试点复选框（主文档 + iframe 内）
3. 按 captcha Provider 分派：
   - `cloudflare.captcharun`：CloudFlare5s API 拿 `cf_clearance` → 注入 cookie + UA → 刷新
   - `turnstile.browser_manual`：页面上等人工完成
   - `turnstile.capsolver/captcharun`：API 拿 token → `_inject_turnstile_token`（写 `cf-turnstile-response` input + 触发 turnstile 回调 + iframe 内注入 + 提交 challenge form）
   - sitekey 找不到 → 回退 CloudFlare5s（有代理时）
4. 轮询至 OTP/密码框出现或 challenge 消失；每 5s 再试点一次复选框
5. 超时 → 报错 + 截图 `data/chatgpt_cf_timeout.png`

---

## 10. 2FA 两种绑定方式

| | http 模式（**强制**，无开关） | browser 模式（`enable_2fa=true` + step06） |
|---|---|---|
| 实现 | `_bind_totp_2fa` 程序化（mfa/enroll → 算码 → activate_enrollment） | step06 页面式（找 UI → 提 secret → 等验证） |
| 耗时 | v0.5.5 实测 6.2s，零 PoW 零邮件 | 慢且依赖页面结构 |
| secret | enroll 响应 JSON 直接取（只出现一次） | 二维码 otpauth / 页面文本正则 |
| 失败影响 | **注册失败（`fail_http_no_2fa`），不产出** | 不影响注册 |
| 推荐 | ✅ | 仅 browser 模式用 |

TOTP 本地实现：RFC 6238（HMAC-SHA1，30s 窗口，6 位码），无第三方库。

---

## 11. 失败分类与排查手册

`failure_class` 取值：`selector_missing` / `timeout` / `page_closed` / `navigation_wrong` / `unexpected_ui` / `captcha_fail` / `email_timeout` / `blocked_cf` / `proxy_dead` / `exception`。

> **v3.0 修复**：`classify_failure` 已移除 `"token"` 关键词——此前正常 token 刷新/获取日志含 "token" 字样会被误判为失败，现已修正。

排查顺序（register-debug 规则）：**任务日志 `step=`/`class=`/`evidence=` → `data/debug/chatgpt_register/<task_id>/<idx>/meta.json` + 截图 + trace.zip → 按 class 对症**。

| 现象（日志关键词） | failure_class | 根因 | 处置 |
|---|---|---|---|
| `CSRF 请求失败/超时` | proxy_dead / blocked_cf | 代理掉线或 CF 拦 curl | 自动整段重试；连续出现换代理出口 |
| `CSRF 无效，signin 被打回` | exception | csrfToken 解析异常（被 CF 顶掉） | 自动整段重试 |
| `OAuth 未进入验证/卡在 authorize` | blocked_cf | sentinel 头/cookie 未生效 | 自动重试（新 Sentinel） |
| `SentinelSDK 未出现` | blocked_cf | CSP 兜底注入失败或代理太慢 | 自动重试；连续失败换出口 |
| `OTP 验证失败 [401]` | email_timeout | 旧码/错码 | 自动补发重试一次 |
| `OTP 验证失败 [403]` | blocked_cf | 缺 sentinel 头或 IP 风控 | 自动整段重试 |
| `OTP 验证失败 [409] invalid_state` | exception | TLS 双发导致会话失效 | 自动整段重试（实测重试后成功） |
| `邮箱验证码获取失败（超时）` | email_timeout | OTP silent-drop（合成 PoW 被深校验拒绝）或 mailnest 迟延 | **不重试**（邮箱已耗）；确认 Node 可用 + `http_sentinel_refresh=true` |
| `创建账号失败 [403] unsupported_country…` | blocked_cf | 出口 IP 被 OpenAI 地区风控 | 自动整段重试（新指纹新会话）；持续 403 换出口国家 |
| `创建账号失败 [409/429]` | exception | 会话冲突/限流 | 自动整段重试 |
| `账号可能已存在（跳转到 log-in）` | unexpected_ui | 邮箱已注册过 | 换邮箱，不重试 |
| `TLS 瞬断，1.5s 后原 session 重试` | — | 代理链路瞬断（5.4% 概率） | 自动（原 session 重试 2 次） |
| `未获取 refresh_token` | — | add-phone 拦截（见 §15） | 非致命，账号仍可用 |
| browser：`Cloudflare 安全验证超时` | captcha_fail / blocked_cf | 人工未过盾 | 换 turnstile Provider 或换代理 |
| browser：`提交邮箱后仍停在入口页` | selector_missing / unexpected_ui | 页面改版或人机验证 | 看截图/trace，改 step02 |
| browser：`等待 Session Token 超时` | timeout | 登录未完成/被风控 | 看 `WARNING_BANNER` 错误与 URL |

**出口质量统计**：看 `egress.jsonl`（§12/§14）——按 `country/result/dur_s` 聚合即可知哪个出口好。

---

## 12. 产出与落盘文件

| 文件 | 内容 | 写入者 |
|---|---|---|
| `data/keys/chatgpt_register/api_keys.txt` | `email\|accessToken`（每行一账号；控制台"最近产出"读它） | 全局 keys 输出 |
| `data/keys/chatgpt_register/refresh_tokens.jsonl` | `email\|refresh_token`（O_APPEND 原子写；**当前恒空**，见 §15） | `project.py::_save_refresh_token` |
| `data/keys/chatgpt_register/egress.jsonl` | 每次尝试一条 JSON：ts/email/proxy(脱敏)/country/ip_tz/attempt/fingerprint/locale/timezone/result(ok/retry/fail/fail_exhausted)/error/dur_s | `_http_engine._append_egress` |
| `data/keys/chatgpt_register/accounts.jsonl` | 账号全量记录（含 extra：mode/plan_type/type/source_type/name/2fa/egress_*） | 全局账号存储 |
| `data/debug/chatgpt_register/<task_id>/<idx>/` | 失败证据：`{step_id}.png` / `.html` / `meta.json`（step/url/title/failure_class/error）/ `trace.zip`（`playwright show-trace` 打开） | RegisterDebug |

`AccountResult` 可观测字段：`failed_step / failure_class / error / evidence_dir / last_url`。

---

## 13. 号池导入与保活链

```text
注册 → api_keys.txt ──(控制台「导入账号池」/ data/_import_c2a2.py)──► chatgpt2api 号池
                 └── refresh_tokens.jsonl（若有 RT，导入时带上 → 自动换新 + keepalive）
```

- 控制台左侧「导出/导入账号池」：`exporter_id=chatgpt2api`（schema 自动绑定），导入后号池自动刷新 `type/quota/status`
- 脚本 `data/_import_c2a2.py`：批量导入 `api_keys.txt`（跳过 SKIP 集合内已死账号），幂等
- **当前无 RT 现实下的正确用法**：注册 → **立即导入** → **立即批量生成**。账号生命周期 = access_token 被 revoke 前（约 5-8h），每个 3h 限流窗口可生成 ~14 张图；3h 后限流恢复可再产（只要未被 revoke）

---

## 14. 实测数据（2026-08-14）

### 吸收 v0.5.5 五能力后的批次（出口 socks5h://192.6.121.16:7890，粘性）

| 邮箱前缀 | 国家 | 指纹 | 尝试 | 结果 | 耗时 |
|---|---|---|---|---|---|
| wv003e2a | US | chrome142 | 1 | ✅ ok | 94.1s（新流程首胜） |
| oh86838 | US | safari18_0 | 3（前两次 403 风控/CF） | ✅ ok | 304.0s |
| dqca5f4 | US | chrome136 | 1 | ✅ ok | 95.1s |
| hj041e8 / ir66eb7a | US | — | — | ✅ ok | ~90-120s |

- **5/5 账号导入号池全部 `status=正常 quota=25`**（此前"1-3 张就死"问题消除）
- 单账号产出实测（ir66eb7a）：连续 **14 张成功**（均值 56s/张）→ 第 15 张 `429 insufficient_quota` → 3h 窗口限制
- 全部账号 RT=0（add-phone 拦截，见 §15）；v0.5.5 自身实测（`data/_gor_results.jsonl`）同样全部 `has_rt: false`

### 历史对照（旧流程，已淘汰）

- 旧无密码 OTP 流程批量注册的 5 账号 7 小时内全死（token 被 revoke）
- `firefox136` impersonate 在当前 curl_cffi 不支持（首行 retry 教训，已由家族表固定版本规避）
- `OTP 409 invalid_state`（TLS 双发）重试后成功——`_TlsRetrySession` 与整段重试链路生效

---

## 15. 已知限制与待办

1. **refresh_token 拿不到（当前最大限制）**：Codex OAuth 普遍命中 `/add-phone` 强制绑手机，去 prompt 重试 2 轮仍拦 → 放弃 RT。v0.5.5 的破法是 **SMS 接码真绑手机**（`_handle_add_phone_via_sms`，SmsBower/HeroSMS），我们未接。**唯一上 RT 的路径 = 接 SMS**（可评估 jichisms 或 SmsBower 通道）。
2. **账号生命周期受 revoke 限制**：无 RT 无法 keepalive，约 5-8h 窗口；用"注册→立即导入→立即生成"吃满窗口。
3. **出口 IP 地区风控**：同 IP 临时 403 `unsupported_country_region_territory`（整段重试可过）；持续 403 换出口国家。
4. **QuickJS 依赖 Node**：Node 缺失时 `http_sentinel_refresh` 静默降级（沿用 playwright 提取的 token，OTP 有 silent-drop 风险）。
5. **browser 模式 step06（页面式 2FA）较旧**：http 模式已强制程序化绑定 2FA。
6. **禁改边界**：不迁入 oumiFree 的 IMAP/GUI/PIX；不复制邮箱/代理/打码实现进项目；Sentinel/HTTP 引擎仅本项目使用。

---

## 16. 成熟度验收

- `http` 与 `browser` 均可作为 **L4 主路径**。
- L1：`total=1 concurrency=1`，`status=ok` 且有 accessToken。
- L2：同配置单并发 ≥5 样本，成功率 ≥80%。
- L3：提并发（先 2 后 N），成功率较 L2 跌幅 ≤15pp。
- **L4 必须从 Web 控制台 `/projects/chatgpt_register` 点「启动任务」（#btnStart）**；仅 API/curl/脚本成功不得认证 L4。
- 任一级失败：先看 `data/debug/chatgpt_register/` 证据，按 §11 修复，同级复验通过再升级。

### L4 验收记录（2026-08-20）

| 指标 | concurrency=2 | concurrency=5 |
|------|---------------|---------------|
| task_id | `e367512d0885` | — |
| 启动方式 | Web 控制台 `#btnStart` | Web 控制台 `#btnStart` |
| 配置 | http 模式 / wary 代理 / mailnest 邮箱 / turnstile.browser_manual | 同左 |
| total / stagger | 10 / 5s | 10 / 5s |
| 成功率 | **10/10 (100%)** | **10/10 (100%)** |
| 耗时 | ~10min | ~6min |
| forwarder 端口 | 10 个唯一端口，无冲突 | 12 个（10 原始 + 2 重试切换），无泄漏 |
| 代理重新获取 | 0 | 2（10 号账号 OTP 409 → 重新获取代理成功） |
| proxy_dead | 0 | 0 |
| 池耗尽 | 0 | 0 |

**结论**：http 主路径 + Web 控制台批量并发，concurrency=2 和 5 均达 100% 成功率，**L4 通过**。wary 代理池表现稳定，forwarder 端口生命周期完整（获取/释放无泄漏），修复后的 per-account state 在并发和重试路径上均无互相覆盖。

**add-phone 拦截**：全部 20 账号的 refresh_token 均命中 `/add-phone`（10/10 + 10/10），与 §15 已知限制一致；accessToken 正常获取不受影响。

---

## 相关文档

- [项目 README](README.md) · [面板说明](ui/help.md) · [UI 规划](ui/schema.json) · [步骤层 README](steps/README.md)
- [HTTP_FINGERPRINT_FIX.md](HTTP_FINGERPRINT_FIX.md)（指纹方案 A→A+ 与死号修复、§11.6 实测修正）
- [2FA_SETUP.md](2FA_SETUP.md)
- 邮箱：[mailsys/mailnest](../../mailsys/mailnest/README.md)；号池导入：`data/_import_c2a2.py`
- 参考实现：oumiFree（Sentinel+API 流程）、gpt-outlook-register v0.5.5（五存活能力）
