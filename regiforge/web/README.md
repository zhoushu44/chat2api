# web

## 职责

Registry 中所有注册项目共用的本地 Web 控制台壳；项目差异由 `projects/<id>/ui/schema.json` 驱动。

## 包含

| 路径 | 说明 |
|------|------|
| `app.py` | FastAPI 入口、REST API、静态资源挂载 |
| `static/index.html` | 双栏单页控制台共用壳 |
| `ui/providers.json` | Captcha / Email / SMS / Proxy / Exporter 全局表单规划 |

## 启动

```powershell
uvicorn web.app:app --host 0.0.0.0 --port 8787
```

Windows 不要加 `--reload`，避免浏览器子进程与 WatchFiles 事件循环冲突。访问 <http://localhost:8787>，或直接打开 `/projects/<project_id>`。

## 项目入口与流程

| 入口 | 主流程 |
|------|--------|
| `/projects/nvidia_build` | 有头浏览器注册、邮箱 OTP、hCaptcha、提取 `nvapi-` Key |
| `/projects/grok_register` | lite HTTP、邮箱 OTP、Turnstile、产出 SSO |
| `/projects/chatgpt_register` | `http` Sentinel/Auth API 或有头 `browser`，产出 accessToken |
| `/projects/sensenova_register` | OAuth2 PKCE HTTP、疾驰短信、SenseNova 滑块、产出 API Key |
| `/projects/tokenrhythm_register` | 有头浏览器、疾驰短信、阿里云滑块、产出 `sk_tr_` API Key |

所有 Registry 项目使用同一双栏壳；任务参数和 Provider 选择按 `ui.project_state.<project_id>` 独立保存。Provider 凭据为全局配置，包含 `captcha.*`、`email.*`、`sms.*`、`proxy.*` 与 `export.*`。

## 日志与产出

前端通过 `GET /api/tasks/{id}/logs?offset=` 轮询增量日志。`ui.keys_output_dir` 留空时写入 `data/keys/<project_id>/api_keys.txt`，非空时写入 `<文件夹>/<project_id>_api_keys.txt`。

导入目标由项目 schema 的 `import.exporter_id` 绑定。`POST /api/export` 返回 `consumed_credentials` 后，可调用 consume 接口同步删除 TXT 与 JSONL 中已消费凭据。

## 主要 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/`、`/projects/{project_id}` | 共用控制台与项目入口 |
| GET | `/api/meta` | Registry 项目、Provider 与 UI 元数据 |
| GET | `/api/projects/{id}/ui` | 单项目 UI 规划 |
| GET | `/api/ui/providers` | Provider 表单规划 |
| GET/PUT | `/api/config` | 本地配置 |
| POST | `/api/verify` | 验证账号凭据 |
| POST | `/api/export` | 导出或导入账号 |
| DELETE | `/api/keys/{project_id}` | 清空指定项目产出 |
| POST | `/api/keys/{project_id}/consume` | 删除已消费凭据 |
| GET/POST | `/api/tasks` | 任务列表 / 启动任务 |
| GET | `/api/tasks/{id}` | 任务状态 |
| POST | `/api/tasks/{id}/stop` | 停止任务 |
| GET | `/api/tasks/{id}/logs?offset=` | 增量日志 |
| GET | `/api/keys` | 全项目产出汇总 |
| GET | `/api/keys/{project_id}` | 单项目产出 |

## 相关

- [浏览器会话](../core/README.md)
- [静态首页](static/README.md)
- [Provider 表单规划](ui/README.md)
