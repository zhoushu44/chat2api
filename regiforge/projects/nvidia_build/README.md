# projects/nvidia_build

## 职责

NVIDIA Build 注册流程，经共用 `TaskRunner` 运行时获取 `nvapi-` API Key。

实测流程使用有头 Chrome（含 `patchright` CDP 修补底座）：邮箱 → 注册表单 → hCaptcha → 邮箱 OTP → API Key。
邮箱 OTP 通过项目级注入的 Provider 获取（推荐 `mailnest`，亦兼容 `cloudflare_worker`）；
代理推荐 `wary`（WARP 粘性代理池）或 `socks5`，留空直连。详见下文「成熟度验收」与 `STEPS.md`。

## 包含

| 路径 | 说明 |
|---|---|
| `project.py` | `PROJECT` 入口，编排 browser / http 双模式；browser 模式注入 `sync_fetch_safe` / `mail_timeout` / `skip_codes` 到 step12 |
| `steps/` | 按编号拆分的页面步骤与私有共享实现（`_flow.py` 含 step11/step12 主体逻辑与踩坑回退） |
| `ui/` | 控制台项目规划与帮助 |
| `STEPS.md` | 步骤参考（含 step11 `/v1/error` 检测、step12.5 验证码无效重试踩坑） |
| `L4_UPGRADE_STATUS.md` | HTTP 模式 L4 升级计划（独立工作，状态见文件本身） |

## 共用能力

| 能力 | Provider |
|---|---|
| 验证码 | `hcaptcha.captcharun` |
| 邮箱 | `mailnest`（推荐）或 `cloudflare_worker` |
| 代理 | `wary`（推荐，WARP 粘性池）或 `socks5`（输入 SOCKS5 链接或动态代理池）；留空直连 |

## 浏览器会话

正式 Web 流程经 `core.browser_runner.browser_session` 固定使用有头、持久、单窗口会话；不加载浏览器插件；项目 schema 的 `task_ui.show_headless=false`，控制台不显示无效的 headless 选项。

项目可选配置 `projects.nvidia_build.browser_channel` 与 `user_agent`：不配置时分别为 `chrome` 和空字符串。共享会话优先探测两个系统 Chrome 路径，未找到时使用非空 channel；仅将 `browser_channel` 配置为空才使用 Playwright 默认 Chromium，并需要 `playwright install chromium`。配置模板未预置 NVIDIA 的这两个可选字段。

`projects.nvidia_build.browser_backend` 可在 `playwright`（默认）与 `patchright`（CDP 泄漏修补，需 `pip install patchright`）间切换浏览器底座；`patchright` 模式下 `browser_session` 会切到 ephemeral `chromium.launch() + new_context()`，避免持久 profile 在多并发下互踩。

## 邮箱超时与重试

- `projects.nvidia_build.mail_timeout`（默认 180s）：`project.py` 通过 `step12_verify_email.set_mail_timeout(...)` 注入给 step12；step12 调 `cf_fetch_code` 时按此超时传给注入器，而非写死 120s。
- step12 验证码无效重试：提交 OTP 后若页面出现「验证码无效」提示（`.notice-alert`），step12 会点「重新请求新验证码」链接，把上一次 code 加入 `skip_codes` 重新调 `cf_fetch_code`，拿到新 code 后重新填+提交；最多重试 1 次。mailnest `_wait_code_sync` 已用 `skip_codes` 过滤已见过的旧码。

如果任务在 `step12` 停止，请先检查邮箱 Provider 是否收到邮件；NVIDIA 的验证码常以 `123-456` 形式出现在 `verification code is` 后。若 CaptchaRun 报 TLS/SSL 连接错误，通常是服务端或网络瞬时中断，可在网络稳定后重试。

## 控制台产出与导出

全局 `ui.keys_output_dir` 只填写文件夹：留空写入 `data/keys/nvidia_build/api_keys.txt`，非空写入 `<文件夹>/nvidia_build_api_keys.txt`。行格式 `email|nvapi-...`（`email|credential`）。控制台预览读取同一文件；导出走全局 `export/file`（NVIDIA 无自动绑定的导入目标）。

## 成熟度验收

| 级 | 结果 | 配置与启动 |
|---|---|---|
| L1 成功 | ✅ 1/1（123s） | `concurrency=1 total=1`，POST /api/tasks |
| L2 稳定 | ✅ 5/5=100% | 同配置 `concurrency=1 total=5` 串行 |
| L3 批量并发 | ✅ 11/12=91.7%（跌幅 8.3% ≤15%） | `concurrency=2 total=6` + `concurrency=3 total=6` |
| **L4 Web 控制台批量并发** | ✅ **7/8=87.5%**（跌幅 12.5% ≤15%） | 共用控制台 `/projects/nvidia_build` 点 `#btnStart`；`total=8 concurrency=3 stagger=3 headless=false`；浏览器底座=patchright + 代理=wary + 邮箱=mailnest + 验证码=hcaptcha.captcharun |

**L4 决定性 batch**：task_id `af9d0773f13b`，由 Web 控制台 `#btnStart` 创建，7 个 `nvapi-` key 写入 `data/keys/nvidia_build/api_keys.txt`。1 个失败为 `mailnest.top` 60s ReadTimeout 邮箱通道外部抖动（非项目代码缺陷）。

L4 验收通过后，同配置下若成功率跌破该级阈值需降回未通过的最高级先复验再升。每次失败先看 `data/debug/nvidia_build/<task_id>/<index>/` 证据（`meta.json` + screenshot + html + trace.zip），按 `failure_class` 对症修复后再同级复验。

## 相关

- [项目层](../README.md)
- [成熟度门禁](../../.trae/skills/project-maturity-gate/SKILL.md)
- [共享浏览器会话](../../core/README.md)
