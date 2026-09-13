# mailsys/tempmail

## 职责

通过 TempMail.lol REST API 创建临时邮箱并轮询接收 xAI/Grok 验证码。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `TempMail.lol EmailProvider` 实现 |
| `__init__.py` | 包标识 |

## Provider

- Provider ID：`tempmail`
- 实现：`provider.py`
- `POST /v2/inbox/create` 创建邮箱
- `GET /v2/inbox?token=...` 轮询邮件
- 支持 xAI 当前 `XXX-XXX` 验证码格式及六位字母数字格式

## 配置

配置键为 `email.tempmail`：

```json
{
  "api_key": "",
  "proxy": "socks5://user:pass@host:port"  // 可选，推荐配置以避免暴露 IP
}
```

API Key 只保存在本地配置或 Web 配置表单中，不写入项目代码和文档。

## 全局代理支持

**TempMail API 请求会自动通过代理**，避免暴露真实 IP：

- `TaskRunner` 启动任务时自动将代理配置注入 `email_cfg["proxy"]`
- `requests` 库使用 `proxies` 参数通过 SOCKS5 代理发送请求
- 解决中国地区 403 限制（TempMail 免费层级禁止中国 IP）

配置方式：在 Web 控制台选择 `SOCKS5 代理` 并填写代理地址，所有 TempMail API 请求自动通过该代理。

## 使用约定

项目流程通过 `ctx.email.generate_address()` 与 `ctx.email.wait_code(...)` 调用，不在 `projects/` 内复制邮箱实现。推荐与 `grok_register` 的 `turnstile.yescaptcha`、`socks5` 配合使用。

## 相关

- [邮箱系统](../README.md)
- [Grok 项目](../../projects/grok_register/README.md)
- [Provider 表单规划](../../web/ui/README.md)
- [全局代理支持](../../core/README.md#全局代理支持)
