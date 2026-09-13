# projects/zcode_register/ui

## 职责

描述 ZCode 项目在共用 Web 控制台中的字段、步骤、能力约束与产出。

## 包含

| 文件 | 说明 |
|------|------|
| `schema.json` | 动态面板规划：邮件/滑块超时、浏览器底座、6 步清单、产出格式、导出 JSON、表格列 |
| `help.md` | 操作帮助：邮箱、滑块、代理、产出与导出 |

## 约定

- 框架固定在 `web/static/index.html`，本目录只写项目差异。
- `task_ui.show_headless=false`：browser 流程固定使用有头浏览器（阿里云滑块需真实交互），页面不显示有头/无头选择。
- 验证码固定 `slider.aliyun`；邮箱为功能级全局下拉（`allowed_email_ids=[]`），控制台默认展示全部邮箱 Provider（mailnest / cloudflare_worker / tempmail / xunmail）；注意 step04 依赖「验证链接」类邮箱，切换到不兼容邮箱前请确认 Provider 是否能返回 verify 链接。
- 代理可选 `none` / `socks5` / `manual_socks5` / `api_socks5` / `clash`（声明在 `allowed_proxy_ids`）。
- 产出格式 `email|accessToken`；表格列含 UserID（`extra.user_id`）。
- 「导出 JSON」按 `export_json.schema=zcode-switcher-account/v1` 导出为 ZCode Switcher 可导入格式。

## 相关

- [项目说明](../README.md)
- [共用 Web 控制台](../../../web/README.md)
- [Provider 表单规划](../../../web/ui/README.md)
