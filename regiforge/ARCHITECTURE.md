# RegiForge 架构

## 定位

本地 FastAPI Web 控制台驱动的注册平台。项目层只实现站点流程；验证码、邮箱和代理通过 `RunContext` 注入的 Provider 复用。

## 目录结构

```text
core/
  base.py                 # Provider / Project / RunContext 抽象
  browser_runner.py       # 共享浏览器会话
  config_store.py         # 本地配置读写（.env 自动填充）
  models.py               # 任务与结果模型
  paths.py                # 运行时路径
  project_ui.py           # 项目、Provider UI 规划加载
  registry.py             # 自动发现 Project / Provider
  step_debug.py           # 步骤可观测（RegisterDebug / 失败证据 / 失败分类）
  task_runner.py          # 单任务调度、日志和产出写入
captcha/<type>/<vendor>/provider.py
mailsys/<backend>/provider.py
sms/<provider_id>/provider.py
proxy/<vendor>/provider.py
verify/<vendor>/provider.py
export/<target>/provider.py
projects/<id>/{project.py, steps/, ui/}
web/
  app.py                  # FastAPI API
  static/index.html       # 控制台首页
  ui/providers.json       # Provider 表单规划
tests/
config/settings.example.json
```

## 核心约定

- **Registry** 自动扫描 `projects/*/project.py`、`captcha/*/*/provider.py`、`mailsys/*/provider.py`、`sms/*/provider.py`、`proxy/*/provider.py`、`verify/*/provider.py`、`export/*/provider.py`，分别暴露 `PROJECT` 或 `PROVIDER`。
- **RunContext** 注入 `captcha`、`email`、`sms`、`proxy` 与任务信息；项目不复制底层能力，仅通过 `ctx.email`、`ctx.sms`、`ctx.proxy`、`ctx.captcha` 复用 Provider。
- **Provider 配置全局共享**，含 `captcha.*`、`email.*`、`sms.*`、`proxy.*`、`verify.*`、`export.*`；项目差异字段放 `projects/<id>/ui/schema.json`。
- **邮箱为功能级全局下拉**：项目 schema 的 `allowed_email_ids` 留空（`[]`）表示不做项目级过滤，控制台邮箱下拉展示全部已注册邮箱 Provider（mailnest / cloudflare_worker / tempmail / xunmail）；仅当流程要求特定格式（如 ZCode 的验证链接、Grok 的字母数字 OTP）时，才在该项目 README 注明默认推荐邮箱，而不是硬编码下拉白名单。
- **Web 项目页** `/projects/<project_id>`：任务参数独立保存（`ui.project_state.<project_id>`），不互覆盖。
- **产出统一** `ui.keys_output_dir`：留空→`data/keys/<project_id>/api_keys.txt`，非空→`<文件夹>/<project_id>_api_keys.txt`。

### 配置路径约定

`data/config.json` 与 `DEFAULT_CONFIG` 使用**嵌套结构**存储多段 ID（与前端 `getByPath` 一致）：

```json
"captcha": {
  "turnstile": {
    "yescaptcha": { "api_key": "...", "api_url": "..." },
    "captcharun": { ... }
  }
}
```

禁止用扁平 key（如 `captcha["turnstile.yescaptcha"]`）。`provider_config()` 兼容两种格式，但新代码统一用嵌套。

### 环境变量（.env）

`core/config_store.py` 启动时 `load_dotenv(ROOT / ".env")`，`DEFAULT_CONFIG` 中所有 `os.getenv()` 调用从 `.env` 读取敏感 Key 作为默认值。`data/config.json` 中已存的具体值会覆盖 env 默认值（`_deep_merge`）。完整变量清单见 [web/ui/README.md](web/ui/README.md#环境变量)。

### 字段默认值

所有 `providers.json` 和 `schema.json` 的字段声明 `default` 值，确保 Web 控制台打开时**无空字段**：

- URL 字段（`api_url`、`base_url`）：`default` 为官方 API 地址
- 数值字段（`timeout`、`poll_interval`）：`default` 为推荐值
- checkbox 字段（`auto_release` 等）：`default` 为推荐开关
- 密钥字段（`api_key`、`password`）：有历史配置时显示配置值，无则留空（安全）

前端 `createFieldControl` 优先读 `config`，为空时回退 `field.default`。

## 共享浏览器会话

`core.browser_runner.browser_session`：固定有头、持久、单窗口，不加载插件。SOCKS5 自动注入远程 DNS。浏览器选择顺序：系统 Chrome → `browser_channel` → Playwright Chromium。

双底座切换：`browser.backend` 或 `projects.<id>.browser_backend` = `playwright` | `patchright`。

## 全局代理

`TaskRunner` 启动时自动将代理注入多数 HTTP 请求：邮箱 `email_cfg["proxy"]`、短信 `sms_cfg["proxy"]`、浏览器 `--proxy-server`、验证码 `httpx/requests`、导出 `httpx/requests`。**MailNest 例外**：`mailnest.top` 为国内直连服务，跳过注入以避免代理访问国内服务超时，如需代理在 `email.mailnest.proxy` 单独配置。

## Web 控制台

共用壳 `web/static/index.html`，主区固定双栏，项目差异由 `projects/<id>/ui/schema.json` + `help.md` 驱动。项目参数 / Provider / 导出一律 `.fields-grid` 双列。

### API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/meta` | 项目、Provider、Exporter 与 UI 元数据 |
| GET | `/api/projects/{id}/ui` | 单项目 UI 规划 |
| GET | `/api/ui/providers` | Provider / Exporter 表单规划 |
| GET/PUT | `/api/config` | 本地配置 |
| POST | `/api/verify` | 验证账号凭据 |
| POST | `/api/export` | 导出 / 导入账号列表 |
| POST | `/api/keys/{project_id}/consume` | 按 credential 同时删除项目 TXT 与结构化 JSONL 产出；响应计数以 TXT 为准 |
| GET/POST | `/api/tasks` | 列表 / 创建任务 |
| GET | `/api/tasks/{id}` | 任务状态 |
| POST | `/api/tasks/{id}/stop` | 停止任务 |
| GET | `/api/tasks/{id}/logs?offset=` | 增量日志 |
| GET | `/api/keys` | 全局产出汇总 |
| GET | `/api/keys/{project_id}` | 单项目产出 |

## 项目成熟度门禁

L1 成功 → L2 稳定 → L3 批量并发 → L4 Web 真实页面批量并发，逐级认定，每项目独立。L4 必须从 `/projects/<project_id>` 页面点「启动任务」。ChatGPT 的 `http` 与 `browser` 均可作为 L4 主路径，但必须满足同级批量并发与成功率门禁。

失败先按 `failure_class` 分流修复，同级复验通过后才升级。详见 `.trae/rules/project-maturity.md`。
