# projects/outlook_register

## 职责

以有头浏览器注册 Outlook / Hotmail 新账号：模拟真人填表（邮箱别名+密码+生日+姓名）→ Microsoft「验证质询」按压验证码 → 绑定辅助邮箱收安全代码，产出 `email@outlook.com : password`（附辅助邮箱）。

迁移自外部仓库 `C:\Users\zs\Desktop\邮箱注册\OutlookRegister`（base_controller.outlook_register + patchright_controller.handle_captcha），按 RegiForge 异步 Playwright + Provider 规范改写。

## 包含

| 文件/子目录 | 说明 |
|-------------|------|
| `project.py` | `PROJECT` 入口，使用 `RegisterDebug` 编排 5 步，`extra` 落盘 `password` / `recovery_email` |
| `steps/` | 打开创建页、填邮箱密码、填姓名、按压验证码、绑定辅助邮箱 |
| `steps/_ms_utils.py` | 随机邮箱别名/强密码/姓名生日 + `Humanizer`（真人鼠标轨迹与输入节奏） |
| `ui/schema.json` | Web 字段、Provider 白名单、步骤与产出规划 |
| `ui/help.md` | 控制台使用说明 |

## Provider 依赖

| 能力 | Provider |
|------|----------|
| 验证码 | `funcaptcha.browser_press`（浏览器内按压「验证质询」，新增于 `captcha/funcaptcha/`） |
| 邮箱 | 功能级全局下拉（`allowed_email_ids=[]`），默认推荐 `tempmail`（`email.tempmail`；中国大陆直连 403，需配置 proxy） |
| 代理 | `none` / `http_proxy` / `socks5` / `clash` |
| 浏览器 | patchright（推荐）/ playwright（`projects.outlook_register.browser_backend`） |

项目内不复制邮箱/代理/打码实现，一律 `ctx.email` / `ctx.proxy` / `ctx.captcha`。

## 产出

- `data/keys/outlook_register/accounts.txt`
- 行格式：`email|password`
- `accounts.jsonl` `extra`：`password`、`recovery_email`、`email_suffix`、`registered_via=browser`

## 踩坑

- 同 IP 短时间多次注册会触发微软「一些异常活动」风控（`blocked_cf`），代理质量决定成功率。
- 出现 `iframe#enforcementFrame` 图片 FunCaptcha 时无法自动通过（当前仅支持按压型）。
- tempmail.lol 从 CN 直连 403，需在 `email.tempmail.proxy` 配置代理。
- mihomo 7890 socks 入口启用凭据时浏览器链路会 `ERR_SOCKS_CONNECTION_FAILED`，已通过本地 HTTP 转发器修复（详见 [proxy/mihomo/README.md](../../proxy/mihomo/README.md)）。

## 相关

- [UI 规划](ui/README.md)
- [按压验证码 Provider](../../captcha/funcaptcha/browser_press/README.md)
- [TempMail Provider](../../mailsys/tempmail/README.md)
