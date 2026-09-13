# projects/chatgpt_register/ui

## 职责

描述 ChatGPT 项目在共用 Web 控制台中的字段、步骤、能力约束与产出。

## 包含

| 文件 | 说明 |
|------|------|
| `schema.json` | 动态面板规划：`register_mode`、超时、浏览器底座、步骤清单、产出格式 |
| `help.md` | 操作帮助：http/browser 差异、mailnest、代理、导出 |

## 约定

- 框架固定在 `web/static/index.html`，本目录只写项目差异。
- 邮箱/代理/验证码/导出凭据**不**在此声明；走全局 `web/ui/providers.json` 与 `email.*` / `proxy.*` / `captcha.*` / `export.*`。
- `allowed_email_ids=[]` 表示邮箱为功能级全局下拉（mailnest / cloudflare_worker / tempmail / xunmail），`required_captcha_types` 为 `turnstile`（http 可不依赖页面打码）。
- 模式相关字段用 `visible_when`（如 `register_mode=http|browser`），由壳层显隐，禁止在 HTML 写死项目分支。
- 产出 `email|accessToken`；导出常用 `export/sub2api`（模板 `$credential` → access_token）。

## 相关

- [项目说明](../README.md)
- [共用 Web 控制台](../../../web/README.md)
- [Provider 表单规划](../../../web/ui/README.md)
