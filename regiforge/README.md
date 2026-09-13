# RegiForge 可插拔注册平台

本地 Web 控制台驱动的注册平台。验证码、邮箱、代理以可插拔 Provider 复用；项目层只实现站点流程。

**正式项目**：NVIDIA Build（`nvapi-` Key）、xAI/Grok（SSO）、ChatGPT/OpenAI（accessToken，`http|browser` 双模式）、商汤 SenseNova（API Key）、基元律动 TokenRhythm（`sk_tr_` Key）、ZCode/Z.ai（accessToken）、Microsoft Outlook/Hotmail（`email|password`）。

## 快速开始

### 1. 安装依赖

```powershell
pip install -r requirements.txt
```

### 2. 配置环境变量（可选，推荐）

在项目根目录创建 `.env`，启动时自动填充 API Key 等配置：

```env
# 验证码
CAPTCHARUN_KEY=你的 CaptchaRun Key
YESCAPTCHA_API_KEY=你的 YesCaptcha Key
CAPSOLVER_KEY=你的 CapSolver Key

# 邮箱
TEMPMAIL_API_KEY=你的 TempMail Key
MAILNEST_API_KEY=你的 MailNest Key
CLOUDMAIL_API_KEY=你的 CloudMail Key
CLOUDMAIL_DOMAIN=你的域名
CLOUDMAIL_API_BASE=你的 CloudMail API 地址
```

### 3. 启动控制台

Windows 可双击 `启动Web.bat`，或执行：

```powershell
uvicorn web.app:app --host 127.0.0.1 --port 8787
```

打开 <http://127.0.0.1:8787> 选择项目，或直接访问 `/projects/<project_id>`。

## 使用说明

- 每个项目的任务参数与 Provider 选择独立保存，不会覆盖其他项目；Provider 凭据全局共享。
- 控制台打开即有默认值（URL、超时、开关等），无需手动填写即可启动任务；API Key 等密钥需首次配置。
- NVIDIA Build 与 ChatGPT browser 使用固定有头页面；Grok 使用 lite HTTP；ChatGPT http 使用协议引擎。
- 推荐组合：Grok `tempmail` + `turnstile.yescaptcha` + `socks5`；ChatGPT 任意功能级邮箱（推荐 `mailnest` / `cloudflare_worker`）+ `turnstile.yescaptcha|captcharun|capsolver` + `socks5`/`http_proxy`；NVIDIA `mailnest`（或 `cloudflare_worker`）+ `hcaptcha.captcharun` + `wary`（或 `socks5`），浏览器底座推荐 `patchright`；SenseNova `jichisms` + `slider.sensenova` + `none`；TokenRhythm `jichisms` + `slider.aliyun` + `none`；ZCode 任意功能级邮箱（默认 `mailnest`，因 step04 依赖验证链接） + `slider.aliyun` + `none`（并发建议 ≤2）。
- ChatGPT 支持 `register_mode=http|browser`：`http` 为 Sentinel + Auth API 路径，`browser` 为有头页面流程。
- 代理支持 SOCKS5 / HTTP/HTTPS / Clash / Wary 粘性池 / 直连，多行轮换与失败自动切换，详见 [proxy/README.md](proxy/README.md)。
- 浏览器、验证码 API、导出 API 统一通过任务代理；MailNest 为国内直连服务，**不走任务代理**（避免 socks5 代理访问国内服务超时），如需代理在 `email.mailnest.proxy` 单独配置。

### 产出与导出

| 项目 | 凭证 | 行格式 |
|------|------|--------|
| NVIDIA Build | `nvapi-` Key | `email|nvapi-...` |
| Grok | SSO | `email|sso` |
| ChatGPT | accessToken | `email|accessToken` |
| SenseNova | API Key | `phone|api_key` |
| TokenRhythm | `sk_tr_` Key | `phone|sk_tr_...` |
| ZCode/Z.ai | accessToken | `email|accessToken` |

- 留空 `keys_output_dir`：`data/keys/<project_id>/api_keys.txt`；非空：`<文件夹>/<project_id>_api_keys.txt`
- `nvidia_api` 验证 NVIDIA Key 连通性
- `file` 输出凭据文件；`chatgpt2api` / `grok2api` / `sub2api` 将凭据导入外部账号池（ChatGPT→chatgpt2api、Grok→grok2api 自动绑定）。导入后是否清理本地产出由 Export Provider 返回的 `consumed_credentials` 决定。

### 运行时路径

| 用途 | 路径 |
|------|------|
| 配置 | `data/config.json` |
| 项目凭据 | `data/keys/<project_id>/api_keys.txt` |
| 失败证据 | `data/debug/<project_id>/<task_id>/<index>/` |
| file 导出 | `data/exports/` |

### 测试

```powershell
py -m unittest discover -s tests -p "test_*.py"
```

## 项目成熟度门禁

每个 `projects/<project_id>` 独立按 L1→L2→L3→L4 逐级验收，禁止跳级。详见 [ARCHITECTURE.md](ARCHITECTURE.md) 与 [门禁规则](.trae/rules/project-maturity.md)。

## 项目结构

```text
RegiForge/
├── core/                         # 抽象、注册表、任务、浏览器会话、配置、步骤可观测
├── captcha/                      # 验证码：类型 -> 服务商
├── mailsys/                      # 邮箱 Provider（cloudflare_worker / mailnest / xunmail / tempmail）
├── sms/                          # 短信接码 Provider（jichisms）
├── proxy/                        # 代理 Provider（none / socks5 / http_proxy / clash / mihomo / wary）
├── verify/                       # 账号可用性验证 Provider
├── export/                       # 文件与外部账号池导出 Provider
├── projects/                     # 六个正式注册流程与项目 UI 规划
├── web/                          # FastAPI 控制台与静态首页
├── scripts/                      # 辅助脚本（代理批量测试、配置更新）
├── tests/                        # 自动化测试
├── docs/                         # 补充文档
├── config/settings.example.json  # 无密钥配置模板
├── 启动Web.bat                   # Windows 启动脚本
├── ARCHITECTURE.md               # 全局架构
└── requirements.txt
```

## 目录 README 索引

| 目录 | 说明 |
|------|------|
| [core/](core/README.md) | 公共内核 |
| [captcha/](captcha/README.md) | 验证码能力 |
| [captcha/cloudflare/](captcha/cloudflare/README.md) | CloudFlare5s 类型 |
| [captcha/cloudflare/captcharun/](captcha/cloudflare/captcharun/README.md) | CaptchaRun (CloudFlare5s) |
| [captcha/cloudflare/flaresolverr/](captcha/cloudflare/flaresolverr/README.md) | FlareSolverr (CloudFlare5s) |
| [captcha/hcaptcha/](captcha/hcaptcha/README.md) | hCaptcha 类型 |
| [captcha/hcaptcha/captcharun/](captcha/hcaptcha/captcharun/README.md) | CaptchaRun (hCaptcha) |
| [captcha/turnstile/](captcha/turnstile/README.md) | Turnstile 类型 |
| [captcha/turnstile/browser_manual/](captcha/turnstile/browser_manual/README.md) | 浏览器内人工完成 |
| [captcha/turnstile/yescaptcha/](captcha/turnstile/yescaptcha/README.md) | YesCaptcha |
| [captcha/turnstile/captcharun/](captcha/turnstile/captcharun/README.md) | CaptchaRun |
| [captcha/turnstile/capsolver/](captcha/turnstile/capsolver/README.md) | CapSolver |
| [captcha/slider/](captcha/slider/README.md) | 图片滑块类型 |
| [captcha/slider/aliyun/](captcha/slider/aliyun/README.md) | 阿里云滑块（yydsocr+非线性映射，TokenRhythm/ZCode） |
| [captcha/slider/sensenova/](captcha/slider/sensenova/README.md) | SenseNova 滑块 |
| [mailsys/](mailsys/README.md) | 邮箱系统 |
| [mailsys/cloudflare_worker/](mailsys/cloudflare_worker/README.md) | Cloudflare Worker 邮箱 |
| [mailsys/mailnest/](mailsys/mailnest/README.md) | MailNest 临时邮箱 |
| [mailsys/tempmail/](mailsys/tempmail/README.md) | TempMail.lol 临时邮箱 |
| [mailsys/xunmail/](mailsys/xunmail/README.md) | 寻邮 Outlook 邮箱 |
| [sms/](sms/README.md) | 短信接码系统 |
| [sms/jichisms/](sms/jichisms/README.md) | 疾驰短信 |
| [sms/haozhuma/](sms/haozhuma/README.md) | 豪猪短信 |
| [proxy/](proxy/README.md) | 代理系统 |
| [proxy/none/](proxy/none/README.md) | 直连 |
| [proxy/socks5/](proxy/socks5/README.md) | SOCKS5 代理 |
| [proxy/http_proxy/](proxy/http_proxy/README.md) | HTTP/HTTPS 代理 |
| [proxy/clash/](proxy/clash/README.md) | Clash 代理 |
| [proxy/mihomo/](proxy/mihomo/README.md) | mihomo WebUI 动态入口 |
| [proxy/wary/](proxy/wary/README.md) | Wary 粘性代理池 |
| [verify/](verify/README.md) | 账号可用性验证 |
| [verify/nvidia_api/](verify/nvidia_api/README.md) | NVIDIA API Key 验证 |
| [export/](export/README.md) | 账号导出 |
| [export/file/](export/file/README.md) | 导出到文件夹 |
| [export/sub2api/](export/sub2api/README.md) | 导入 Sub2API |
| [export/grok2api/](export/grok2api/README.md) | 导入 Grok2API |
| [export/chatgpt2api/](export/chatgpt2api/README.md) | 导入 chatgpt2api |
| [projects/](projects/README.md) | 项目层 |
| [projects/nvidia_build/](projects/nvidia_build/README.md) | NVIDIA Build |
| [projects/nvidia_build/steps/](projects/nvidia_build/steps/README.md) | NVIDIA 步骤 |
| [projects/nvidia_build/ui/](projects/nvidia_build/ui/README.md) | NVIDIA UI 规划 |
| [projects/grok_register/](projects/grok_register/README.md) | xAI/Grok |
| [projects/grok_register/steps/](projects/grok_register/steps/README.md) | Grok 步骤 |
| [projects/grok_register/ui/](projects/grok_register/ui/README.md) | Grok UI 规划 |
| [projects/chatgpt_register/](projects/chatgpt_register/README.md) | ChatGPT/OpenAI |
| [projects/chatgpt_register/steps/](projects/chatgpt_register/steps/README.md) | ChatGPT 步骤 |
| [projects/chatgpt_register/ui/](projects/chatgpt_register/ui/README.md) | ChatGPT UI 规划 |
| [projects/sensenova_register/](projects/sensenova_register/README.md) | 商汤 SenseNova |
| [projects/sensenova_register/steps/](projects/sensenova_register/steps/README.md) | SenseNova 步骤 |
| [projects/sensenova_register/ui/](projects/sensenova_register/ui/README.md) | SenseNova UI 规划 |
| [projects/tokenrhythm_register/](projects/tokenrhythm_register/README.md) | 基元律动 TokenRhythm |
| [projects/tokenrhythm_register/steps/](projects/tokenrhythm_register/steps/README.md) | TokenRhythm 步骤 |
| [projects/tokenrhythm_register/ui/](projects/tokenrhythm_register/ui/README.md) | TokenRhythm UI 规划 |
| [projects/zcode_register/](projects/zcode_register/README.md) | ZCode / Z.ai |
| [projects/zcode_register/steps/](projects/zcode_register/steps/README.md) | ZCode 步骤 |
| [projects/zcode_register/ui/](projects/zcode_register/ui/README.md) | ZCode UI 规划 |
| [projects/outlook_register/](projects/outlook_register/README.md) | Microsoft Outlook / Hotmail |
| [web/](web/README.md) | Web 控制台 |
| [web/static/](web/static/README.md) | 静态首页 |
| [web/ui/](web/ui/README.md) | Provider 表单规划 |
| [docs/anti-detect/](docs/anti-detect/README.md) | 指纹与防抓知识库（底座/出口/验证码/CF 排查） |
| [config/](config/README.md) | 配置模板 |
| [tests/](tests/README.md) | 自动化测试 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 全局架构 |
