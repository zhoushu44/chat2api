# export/grok2api

## 职责

按 GPTGrok2API 的真实管理接口导入 Grok Web/Console SSO 或 Grok Build OAuth 凭据，并返回导入数量。Grok 项目（`projects/grok_register`）自动绑定本导出器，在最近产出区点击「导入到 Grok2API」按钮即可执行导入；导入成功的产出会从最近产出中逐条删除，失败或部分成功的凭据会保留。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `Grok2ApiExportProvider` 实现 |
| `__init__.py` | 包标识 |

## 配置

- `export.grok2api.base_url`：GPTGrok2API 根地址
- `export.grok2api.admin_password`：目标 Grok2API 后台 `/api/admin/v1` 使用的管理员 JWT，发送为 `Authorization: Bearer <JWT>`

当前按项目自动导入：`grok_register` 调用 `/api/admin/v1/accounts/web/import`，将最近产出的 SSO Token 按“每行一个 Token”写入 TXT，通过 multipart 的 `files` 字段上传，不使用 `email|sso` 格式，也不需要选择账号类型。接口返回全部成功后，最近产出才会删除对应记录。

## 全局代理支持

**Grok2API 导入请求会自动通过代理**（如果配置了 SOCKS5 代理）：

- Grok2API Provider 使用 `httpx` 发送请求
- `httpx` 自动使用系统代理或配置代理
- 统一流量出口，避免暴露真实 IP

配置方式：在 Web 控制台选择 `SOCKS5 代理` 并填写代理地址，所有 Grok2API 请求自动通过该代理。

## 相关

- [导出系统](../README.md)
- [全局代理支持](../../core/README.md#全局代理支持)