# Grok lite 注册步骤

| 步骤 | 实现位置 | 说明 |
|------|----------|------|
| 01 | `steps/_lite_engine.py` | Bootstrap 注册页，获取元数据、sitekey、Next.js action 与 router state |
| 02 | `steps/_lite_engine.py` | `ctx.email` 创建邮箱，并通过 gRPC-web 发送验证码 |
| 03 | `steps/_lite_engine.py` | `ctx.email.wait_code` 收取 OTP，并通过 gRPC-web 校验 |
| 04 | `steps/_lite_engine.py` | `ctx.captcha` 解 Turnstile，调用 Server Action 创建账号 |
| 05 | `steps/_lite_engine.py` | 解析 RSC、set-cookie 链、SSO 跳转与 cookie jar，取得 JWT |

项目只保留 HTTP lite 流程，不再维护旧 browser 步骤或旧协议引擎。所有步骤由 `project.py` 统一编排，并通过 `RegisterDebug` 记录失败证据。

Cloudflare 返回 `blocked_cf` 时应检查代理出口；邮箱超时检查 `tempmail`，验证码失败检查 `turnstile.yescaptcha`。不要在项目目录复制 Provider 实现。
