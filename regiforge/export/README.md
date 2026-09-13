# export

## 职责

账号导出层。每个 Provider 将已有账号凭据写入文件或导入外部账号池，不负责注册和可用性验证。

## 包含

| 子目录 | Provider ID | 说明 |
|---|---|---|
| [`file/`](file/) | `file` | 写出 `email|credential` 文件 |
| [`sub2api/`](sub2api/) | `sub2api` | 调用 Sub2API 管理端批量建号接口 |
| [`grok2api/`](grok2api/) | `grok2api` | 调用 Grok2API 管理端 JSON 接口导入 SSO/OAuth |
| [`chatgpt2api/`](chatgpt2api/) | `chatgpt2api` | 调用 chatgpt2api 管理端 `POST /api/accounts` 导入 accessToken |

## 约定

路径为 `export/<target>/provider.py`，导出 `PROVIDER` 并实现 `async export(accounts)`；全局配置位于 `export.<id>`。通过 `POST /api/export` 或控制台「导入」按钮调用；外部系统管理员令牌仅能保存在对应全局配置中。

导入目标由项目 `ui/schema.json` 的 `import.exporter_id` 自动绑定（ChatGPT→`chatgpt2api`、Grok→`grok2api`、NVIDIA 无导入），不再手选。控制台右栏「Provider 配置」区按 `web/ui/providers.json` 的 `when.exporter_id` 显示对应参数：

| 目标 | 典型参数 |
|------|----------|
| `file` | 文件夹路径、文件名 |
| `sub2api` | 根地址、管理员令牌、单条账号模板（`$email` / `$credential` / `$index`） |
| `grok2api` | 根地址、管理密钥（JWT） |
| `chatgpt2api` | 根地址、管理员密钥（作为 Bearer 值发送） |

产出行统一按 `email|credential` 解析后送入对应 Provider。Exporter 通过 `ExportResult.consumed_credentials` 声明远端已接收、允许从本地产出删除的凭据；Web 前端只根据该字段调用 consume，不根据 `status` 或 `imported` 推断清理范围。

## 相关

- [公共内核](../core/README.md)
