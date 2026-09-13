# Outlook / Hotmail 注册

通过 `outlook.live.com` 官方创建账号入口注册新的 Outlook 邮箱：

1. 打开 `https://outlook.live.com/mail/0/?prompt=create_account`，接受「同意并继续」
2. 填写随机邮箱别名（12–14 位小写+少量数字）+ 强密码；选 `@hotmail.com` 时自动切换域名
3. 部分地区/随机出现生日表单（年/月/日），自动填写随机出生日期
4. 填写姓/名资料，保证总操作时长 ≥ `bot_protection_wait` 后提交
5. 出现「验证质询」按压验证码 → `captcha.funcaptcha.browser_press` 在浏览器内按压通过
6. 进入「让我们来保护你的帐户」→ 绑定辅助邮箱（temp-mail）并回填 Microsoft 安全代码
7. **step06 OAuth**（可选）：注册成功后自动跑 Public Client OAuth 拿 `refresh_token` → 写入 `extra.refresh_token`，供 outlookEmailPlus 导入

## 依赖 Provider

| 能力 | Provider | 说明 |
|------|----------|------|
| 邮箱 | `email.tempmail` | 创建临时邮箱收 Microsoft 安全代码；**中国大陆直连 tempmail.lol 会 403**，需在 Provider 配置填 `proxy`（如 socks5://…） |
| 邮箱 | `email.mailnest` | MailNest 临时邮箱；`outlook_register` 默认 `microsoft001`，**必须用 microsoft 系列 product_code**，否则过滤规则不收 outlook.com，表现为 `wait_code` 一直超时 |
| 验证码 | `captcha.funcaptcha.browser_press` | 浏览器内按压「验证质询」，无外部打码成本 |
| 代理 | `proxy.socks5` / `proxy.http_proxy` / `proxy.clash` | 建议使用；IP 质量与成功率强相关 |
| 浏览器 | patchright（推荐）/ playwright | Microsoft 对自动化浏览器检测较严 |

## 成功凭证

`email@outlook.com : password`（`apikey` 槽位存密码），辅助邮箱记录在 `extra.recovery_email`。
产出写入 `data/keys/outlook_register/accounts.txt`。

**导入 outlookEmailPlus（5001）**还需以下字段（由 step06 OAuth 自动写入 `extra`）：

| 字段 | 来源 | 说明 |
|---|---|---|
| `extra.refresh_token` | step06 OAuth 兑换 | **必须** |
| `extra.client_id` | `projects.outlook_register.oauth_client_id` | Azure 应用 ID |
| `extra.tenant` | `projects.outlook_register.oauth_tenant`（默认 `consumers`） | 个人账号固定 |
| `extra.scope` | `projects.outlook_register.oauth_scope` | 必须含 `offline_access` |

完整字段说明：`C:\知识库\史蒂夫周\注册机\导出\outlook_register 账号字段说明.md`。
Azure 应用注册步骤：`C:\知识库\史蒂夫周\注册机\导出\Azure 应用注册 — outlook_register OAuth 配置.md`。

## 踩坑

- **IP 风控**：同 IP 短时间多次注册会触发「一些异常活动」/「请重试」→ 换代理，`failure_class=blocked_cf`。
- **验证码类型**：出现 `iframe#enforcementFrame` 图片 FunCaptcha 时无法自动通过（当前仅支持按压型）。
- **安全代码**：验证码 6 位，来自主题为「个人 Microsoft 帐户安全代码」的邮件；超时可调大 `mail_timeout`。
- **并发**：建议先 `total=1, concurrency=1` 调试，跑通后再逐步提并发。
