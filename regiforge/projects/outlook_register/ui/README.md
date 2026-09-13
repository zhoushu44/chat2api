# projects/outlook_register/ui

## 职责

描述 Outlook 注册项目在共用 Web 控制台中的字段、步骤、能力约束与产出。

## 包含

| 文件 | 说明 |
|------|------|
| `schema.json` | 动态面板规划：邮箱后缀/操作时长/超时/重试/浏览器底座、5 步清单、产出格式、表格列 |
| `help.md` | 操作帮助：邮箱、验证码、代理、产出与踩坑 |

## 约定

- 框架固定在 `web/static/index.html`，本目录只写项目差异。
- `task_ui.show_headless=false`：browser 流程固定使用有头浏览器（Microsoft 风控 + 按压验证码需真实浏览器），页面不显示有头/无头选择。
- 验证码固定 `funcaptcha.browser_press`；邮箱为功能级全局下拉（`allowed_email_ids=[]`），目前默认推荐 `tempmail`（注意 tempmail.lol 从 CN 直连 403，需在 `email.tempmail.proxy` 配置代理）。
- 代理可选 `none` / `http_proxy` / `socks5` / `clash`。
- 产出格式 `email|password`；表格列含辅助邮箱（`extra.recovery_email`）。
- `browser_backend` 默认 `patchright`（外部仓库实测推荐），可切换 playwright。

## 相关

- [项目说明](../README.md)
- [共用 Web 控制台](../../../web/README.md)
- [Provider 表单规划](../../../web/ui/README.md)
