# captcha/turnstile/yescaptcha

## 职责

通过 YesCaptcha API 自动解决 Cloudflare Turnstile 挑战。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `YesCaptcha Turnstile Provider` 实现 |
| `__init__.py` | 包标识 |

## Provider

- Provider ID：`turnstile.yescaptcha`
- 实现：`provider.py`
- 支持 `TurnstileTaskProxylessM1`，并可回退到标准 `TurnstileTaskProxyless`
- xAI/Grok 注册页没有返回 sitekey 时，使用 `accounts.x.ai` 的已知 sitekey 兜底

## 配置

配置键为 `captcha.turnstile.yescaptcha`：

```json
{
  "api_key": "",
  "api_url": "https://api.yescaptcha.com"
}
```

API Key 只保存在本地配置或 Web 配置表单中，不写入项目代码和文档。

国内用户可使用 `https://cn.yescaptcha.com`。

## 使用约定

项目流程通过 `ctx.captcha.solve(...)` 调用，不在 `projects/` 内复制 YesCaptcha 实现。

## 全局代理支持

`TaskRunner` 启动任务时自动将当前任务的代理注入 `captcha_cfg["proxy"]`，YesCaptcha API 请求会通过该代理发送。代理 URL 中的 `%XX` 编码会自动解码。

若代理访问 YesCaptcha 不稳定，可配置直连代理（`proxy.none`）或换用 `turnstile.captcharun`。

## 相关

- [Turnstile 类型](../README.md)
- [Grok 项目](../../../projects/grok_register/README.md)
- [Provider 表单规划](../../../web/ui/README.md)
- [全局代理支持](../../../core/README.md#全局代理支持)
