# web/static

## 职责

共用控制台前端静态文件。

## 包含

| 文件 | 说明 |
|---|---|
| `index.html` | 单页 UI：项目导航、验证码/邮箱/代理、任务启停、日志、产出、导出 |

## 说明

- 无构建步骤，FastAPI 直接挂载 `/static`，根路径返回 `index.html`；`/projects/<id>` 同一页。
- 页面通过 REST API 获取元数据、保存配置和管理任务；Provider / Exporter 列表来自 `/api/meta`，不硬编码项目名。
- 顶部项目导航 pill + 下拉框切换项目；三项目共用同一布局（左：任务/产出，右：步骤/说明/Provider 配置/导入参数），**禁止** ChatGPT 等项目改成单栏。
- 项目参数 / Provider / 导入参数统一 `.fields-grid` **双列**；仅 textarea 或 `full/span:2` 跨两列。
- 项目字段支持 schema `visible_when`（按其它字段值显隐，如 `register_mode`）；隐藏不删配置值。
- 导入目标由项目 `ui/schema.json` 的 `import.exporter_id` 自动绑定（ChatGPT→chatgpt2api、Grok→grok2api、NVIDIA 无），右栏「Provider 配置」区按 `when.exporter_id` 显示 `web/ui/providers.json` 中对应参数组；最近产出区的「导入到 xxx」按钮读取当前项目 keys 后 `POST /api/export`。响应包含非空 `consumed_credentials` 时，页面再调用 `POST /api/keys/{project_id}/consume` 并刷新最近产出；页面不根据 `status` 判断是否清理。
- 「注册账号（全局）」区块汇总所有注册项目的账号产出（`GET /api/keys`），按项目分列显示，刷新产出时同步更新。
- 日志通过 `GET /api/tasks/{id}/logs?offset=` 轮询增量获取，不使用 WebSocket 或 SSE。
- 通用任务参数由项目 schema 的 `task_ui` 控制；当前三个项目均隐藏无效的 `headless` 选择，启动时固定提交 `headless=false`。NVIDIA Build 与 ChatGPT browser 使用固定有头页面；Grok 使用 lite HTTP；ChatGPT http 使用协议引擎。
- 全局产出目录通过统一的"选择文件夹"控件设置，绑定 `ui.keys_output_dir`：留空写 `data/keys/<project_id>/api_keys.txt`，非空写 `<文件夹>/<project_id>_api_keys.txt`。
- 顶栏与任务区已精简：移除顶栏副标题、独立页提示和各字段冗余 help 文本，减少视觉噪声。

## 相关

- [后端](../README.md)
