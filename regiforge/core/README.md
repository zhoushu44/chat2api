# core

## 职责

公共内核：定义 Provider / 项目抽象，管理配置、自动发现、任务调度、产出路径和共享浏览器会话。

## 包含

| 文件 | 说明 |
|---|---|
| `__init__.py` | 包标识 |
| `base.py` | `CaptchaProvider`、`EmailProvider`、`SmsProvider`、`ProxyProvider`、`VerificationProvider`、`ExportProvider`、`RegistrationProject`、`RunContext` |
| `models.py` | `TaskConfig`、`TaskStatus`、`AccountResult`、`VerificationResult`、`ExportResult`、`ProxyInfo` |
| `registry.py` | 扫描并注册 projects、captcha、mailsys、sms、proxy、verify、export |
| `config_store.py` | `data/config.json` 读写与默认配置合并；**启动时从 `.env` 或系统环境变量自动填充 API Key 等配置** |
| `task_runner.py` | 创建、并发执行、停止任务；保存内存日志缓冲与产出 |
| `paths.py` | 根路径及 `data/keys`、`data/tasks`、`data/logs`、`data/debug` 运行时路径 |
| `project_ui.py` | 项目与 Provider UI 规划加载 |
| `browser_runner.py` | NVIDIA Build、ChatGPT browser 与 TokenRhythm 的共享有头浏览器会话；Grok lite、SenseNova HTTP 不使用 |
| `step_debug.py` | 注册步骤可观测：`RegisterDebug`（START/OK/FAIL 日志、失败截图/HTML/meta、可选 `trace.zip`、失败分类） |

## 注册失败证据

失败证据写入 `data/debug/<project_id>/<task_id>/<index>/`，包括 `meta.json`、截图、HTML 与可选 `trace.zip`。

`AccountResult` 的可观测字段包括 `failed_step`、`failure_class`、`error`、`evidence_dir`、`last_url`。配置见 `debug.*`（`settings.example.json`）；规则 `.trae/rules/register-debug.md`，修流程 skill `fix-register-flow`。

## 浏览器会话

`browser_runner.browser_session` 固定启动有头、持久、单窗口会话，不加载浏览器插件。当前项目 schema 已隐藏不生效的通用 `headless` 选择；仅项目明确声明 `task_ui.show_headless=true` 时，前端才允许提交无头任务。它依次探测系统 Chrome 路径；未找到时使用非空 `browser_channel`（项目默认 `chrome`）；仅 `browser_channel` 为空才落到默认 Chromium。

### 双底座切换（playwright / patchright）

| 配置 | 说明 |
|------|------|
| `browser.backend` | 全局默认，`playwright` 或 `patchright` |
| `projects.<id>.browser_backend` | 项目覆盖；留空则跟随全局 |

解析顺序：`browser_session(browser_backend=…)` 显式参数 → 项目 `browser_backend` → 全局 `browser.backend` → `playwright`。
`patchright` 需 `pip install patchright`；ChatGPT HTTP 模式取 Sentinel 走同一套切换。

### SOCKS5 远程 DNS

Chrome 不支持 `socks5h://` 协议前缀。`browser_session` 在检测到 `socks5://` 代理时自动注入 `--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1`，让 Chrome 把原始主机名发给 SOCKS5 代理解析，等效于 `socks5h` 的远程 DNS 行为。`socks5` Provider 的浏览器链路受益，用户无需额外配置。

## 产出

`TaskRunner` 对所有项目统一使用 `ui.keys_output_dir`：控制台统一使用“选择文件夹”控件设置。留空写入 `data/keys/<project_id>/api_keys.txt`，非空写入 `<文件夹>/<project_id>_api_keys.txt`；目录自动创建，控制台预览读取同一位置。

## 全局代理支持

`TaskRunner` 启动任务时，会自动将代理配置注入多数 HTTP 请求：

1. **邮箱 Provider**：`email_cfg["proxy"]` 注入代理地址，TempMail / Cloudflare Worker / 寻邮 的 `requests` 调用自动使用代理；**MailNest 例外**（见下）
2. **短信 Provider**：`sms_cfg["proxy"]` 注入代理地址，疾驰短信等 `requests` 调用自动使用代理
3. **浏览器会话**：`browser_session` 启动 Chrome 时注入 `--proxy-server` 参数
4. **验证码 Provider**：YesCaptcha / CaptchaRun 等通过 `httpx` / `requests` 请求时自动使用代理；`slider.aliyun` 的验证码图片通过 `page.context.request` 沿当前浏览器上下文网络路径下载，可选 yydsocr 识别请求由 Provider 自身 `requests` 发出

**除 MailNest 外的 HTTP 流量统一通过代理**，避免暴露真实 IP。

### MailNest 直连例外

`mailnest.top` 为国内直连服务，`TaskRunner` **不**向 mailnest 注入任务代理（`config.email_id == "mailnest"` 时跳过），避免 socks5 代理无法访问国内服务而超时。若本机需经代理访问 mailnest.top，在配置键 `email.mailnest.proxy` 单独指定（与任务代理解耦）。

### 带认证代理自动转换（2026-07-27 修复）

SOCKS5 Provider 和邮箱 Provider 都支持自动转换带认证的 SOCKS5 代理：

- **输入**：`socks5://username:password@host:port`
- **优先**：本地 HTTP 转发器 `http://127.0.0.1:xxxx`（免认证，兼容性最好）
- **降级**：`socks5h://username:password@host:port`（转发器失败时自动回退）
- **支持库**：`curl_cffi`、Playwright、`requests` 均支持这两种格式

### 多代理轮换与失败切换

当 SOCKS5 Provider 配置多行代理时：

- **轮换计算**：`task_runner` 根据 `proxy._proxy_index - 1` 计算当前使用的代理
- **失败标记**：`failure_class` ∈ {`proxy_dead`, `proxy_reset`, `tls_error`, `exception`} 时加入 `_failed_proxies`
- **成功恢复**：`result.apikey` 存在时从失败集合移除
- **日志输出**：`[idx] 代理 socks5://... 标记为失败，自动切换到下一个`

### API 动态获取代理

SOCKS5 Provider 支持从 API 动态获取代理：

- **配置路径**：`proxy.socks5.api_url`
- **认证字段**：`proxy.socks5.api_key`（可选）
- **工作机制**：HTTP GET → 自动解析（纯文本/JSON/HTML）→ 随机选择 → 标准化为 `socks5://`
- **认证处理**：API 返回的带认证代理也会被转换为本地 HTTP 转发器
- **失败处理**：API 请求失败时抛出异常，任务标记为失败

## 相关

- [架构总览](../ARCHITECTURE.md)
- [控制台](../web/README.md)
