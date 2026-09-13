# projects/chatgpt_register/steps

## 职责

ChatGPT 注册流程：browser 编号步骤 + http（Sentinel / Auth API）私有引擎。

## 包含

| 文件 | 说明 |
|---|---|
| `_fingerprint.py` | **http**：A+ 随机指纹。多家族（chrome/firefox/safari）随机一套完整画像（UA/TLS impersonate/sec-ch-ua/语言/时区/屏幕/硬件），`detect_country` 按代理出口国家探测并地理联动；curl 与 Sentinel 浏览器共用同一套（见 [HTTP_FINGERPRINT_FIX.md](../HTTP_FINGERPRINT_FIX.md)） |
| `_sentinel.py` | **http**：短生命周期浏览器提取 OpenAI Sentinel Token；取 token 后顺带访问 `chatgpt.com/api/auth/csrf`，让真 Chrome 通过 CF 挑战取得 `__cf_bm`/`cf_clearance`，供 curl_cffi 复用（同 UA + 同代理 IP）。`extract_sentinel(fingerprint=fp)` 时 context 的 UA/locale/timezone/viewport 与硬件画像全部取指纹 |
| `_http_engine.py` | **http**：curl_cffi 调 Auth API；邮箱/代理由 ctx 注入；authorize 403 整段重试。`_apply_sentinel_cookies` 把 Sentinel 浏览器 cookie（含 CF 放行 cookie）挂到多域。请求头统一走 `_browser_headers(fp)`（`sec-ch-ua*` + `sec-fetch-*`），TLS 指纹取 fp 精确版本；每次注册随机一套指纹（方案 A+，见 [HTTP_FINGERPRINT_FIX.md](../HTTP_FINGERPRINT_FIX.md)） |
| `step01_open_login.py` | **browser**：打开登录/注册入口 |
| `step02_submit_email.py` | **browser**：提交邮箱并处理 Cloudflare |
| `step03_verify_email.py` | **browser**：收 OTP 并填写 |
| `step04_complete_profile.py` | **browser**：资料与引导 |
| `step05_extract_session.py` | **browser**：读 accessToken |
| `_browser.py` | Playwright 页面辅助 |
| `_challenge.py` | Cloudflare / Turnstile 协调 |

## 并发安全（v3.0 修复）

`_challenge.py` 中的 `acquired_proxy` 和 `last_failure_class` 已从共享 `config` 字典改为 `RunContext` per-account 局部字段（`ctx.acquired_proxy` / `ctx.last_failure_class`），避免多账号并发时互相覆盖代理状态和失败分类。涉及 `project.py` 6 处 + `_challenge.py` 2 处。

## 模式

- `register_mode=http`：`_sentinel` → `_http_engine`（oumiFree 兼容），不点页面盾。
- `register_mode=browser`：step01–05 有头流程，可能需要手动过 CF。

邮箱一律 `ctx.email`（mailnest），禁止在本目录复制取件实现。  
代理一律调用方注入的 `ProxyInfo`；http 引擎内部将 `socks5://` 规范为 `socks5h://`。

## 相关

- [项目说明](../README.md)
- 参考：[oumiFree](https://github.com/zbqoumi/oumiFree)（仅流程思路）
