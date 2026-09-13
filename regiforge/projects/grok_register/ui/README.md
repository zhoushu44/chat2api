# projects/grok_register/ui

## 职责

描述 Grok lite 项目在共用 Web 控制台中的字段、步骤、能力约束与产出。

## 包含

| 文件 | 说明 |
|------|------|
| `schema.json` | 动态面板规划：邮箱超时、Turnstile 超时、User-Agent、lite 步骤与产出格式 |
| `help.md` | 操作帮助：邮箱、Turnstile、代理、产出与导出 |

## 约定

- 框架固定在 `web/static/index.html`，本目录只写项目差异。
- `schema.json` 的 `task_ui.show_headless=false` 表示 lite HTTP 不启动注册浏览器，页面不显示有头/无头选择。
- 邮箱、代理、验证码与导出配置走全局 Provider 表单；`allowed_email_ids=[]` 表示邮箱为功能级全局下拉（mailnest / tempmail / cloudflare_worker / xunmail）。
- 推荐使用 `tempmail`、`turnstile.yescaptcha` 与 `socks5`；项目不复制 Provider 实现，也不限制邮箱下拉。
- 产出格式为 `email|sso`，导出继续使用共用导出能力。

## 相关

- [项目说明](../README.md)
- [共用 Web 控制台](../../../web/README.md)
- [Provider 表单规划](../../../web/ui/README.md)
