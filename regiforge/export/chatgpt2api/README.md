# export/chatgpt2api

## 职责

调用 chatgpt2api（basketikun/chatgpt2api）管理端 `POST /api/accounts` 批量导入 ChatGPT accessToken。导入后 chatgpt2api 自动 refresh_accounts 检测真实 type/quota/status。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `ChatGPT2ApiExportProvider` 实现 |
| `__init__.py` | 包标识 |

## 接口

```
POST {base_url}/api/accounts
Authorization: Bearer {admin_password}
Content-Type: application/json

{"accounts": [{"access_token": "...", "email": "...", "type": "free", "source_type": "web"}]}
```

Provider 接口支持从 `AccountResult.extra` 读取 `type` / `source_type`，缺省为 `free` / `web`。当前 Web `/api/export` 请求只传递 `email` 与 `credential`，不会传递结构化账号的 `extra`，因此从控制台导入时实际发送 `type=free`、`source_type=web`。

## 配置

- `export.chatgpt2api.base_url`：chatgpt2api 根地址（不带尾斜杠）
- `export.chatgpt2api.admin_password`：后台管理员密钥，只填密钥本体；发送为 `Authorization: Bearer <密钥>`（`require_admin` 校验）

`admin_password` 是为兼容现有配置保留的字段名，值不要求必须是 JWT。管理员密钥只保存在本地配置或 Web 配置表单中，不写入项目代码和文档。

导入结果按整批账号处理：新增或已存在而被跳过的账号都会计入已处理数量；只要整批账号都已被远端新增或跳过，控制台就会清理对应的本地产出。远端 refresh 报错（例如 `token invalidated`）会保留在结果详情中，但不会阻止已接收账号的本地产出清理；未被远端接收的账号仍会保留。

## 控制台用法

ChatGPT 项目（`projects/chatgpt_register`）的 `ui/schema.json` 已将 `import.exporter_id` 设为 `chatgpt2api`，导入目标自动绑定，无需手选。在右栏「Provider 配置」区填写根地址与管理员密钥，点击最近产出区的「导入到 chatgpt2api」按钮执行导入。前端仅在响应包含 `consumed_credentials` 时清理本地产出；当前 Provider 只在本次请求中的账号全部被远端新增或跳过时返回整批凭据，因此带远端刷新错误的 `partial` 结果也可能清理整批，而仅处理部分账号的 `partial` 结果不会清理。

## 相关

- [导出系统](../README.md)
- [ChatGPT 注册项目](../../projects/chatgpt_register/README.md)
