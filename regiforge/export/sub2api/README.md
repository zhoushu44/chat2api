# export/sub2api

## 职责

调用 Sub2API 管理端 `POST /api/v1/admin/accounts/batch` 批量创建账号。模板内置固定为 OpenAI OAuth（`access_token=$credential`），不再暴露自定义模板字段。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `Sub2ApiExporter` 实现（含 `DEFAULT_TEMPLATE`） |
| `__init__.py` | 包标识 |

## 配置

- `export.sub2api.base_url`：Sub2API 根地址（不带尾斜杠）
- `export.sub2api.admin_access_token`：管理员访问令牌

管理员访问令牌只保存在本地配置或 Web 配置表单中，不写入项目代码和文档。

## 内置模板

`provider.py` 的 `DEFAULT_TEMPLATE` 固定为：

```json
{
  "name": "$email",
  "platform": "openai",
  "type": "oauth",
  "credentials": { "access_token": "$credential" }
}
```

`$email`、`$credential`、`$index` 在导入时被替换。ChatGPT 产出 keys 行是 access token（`$credential`）。若目标 Sub2API 实例要求 OAuth 刷新令牌，需修改 `DEFAULT_TEMPLATE` 源码，仅有 access token 不能作为长期可用的 OAuth 账号导入。

## 控制台用法

Sub2API 为通用导出目标（非项目自动绑定），在右栏「Provider 配置」区填根地址与管理员令牌，通过 `POST /api/export` 调用。

## 相关

- [导出系统](../README.md)
