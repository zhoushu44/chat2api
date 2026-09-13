# projects/grok_register

## 职责

实现 xAI/Grok 注册流程；邮箱、代理与 Turnstile 均通过 `RunContext` 的共用 Provider 使用，成功后产出 SSO。

## 当前流程

项目仅保留 lite HTTP 协议流程，不再包含旧的 browser/http 双模式：

1. `curl_cffi` 获取 xAI 注册页元数据、sitekey 与 Next.js action
2. 通过 `ctx.email` 创建邮箱并收取验证码
3. 通过 gRPC-web 校验邮箱验证码
4. 通过 `ctx.captcha` 解 Turnstile 并创建账号
5. 从 RSC、set-cookie 链与 SSO 跳转中提取 JWT

正式入口为共用 Web 控制台与 `TaskRunner`，项目内不复制邮箱、代理或验证码服务商实现。

## 包含

| 路径 | 说明 |
|---|---|
| `project.py` | `PROJECT` 入口，编排 lite 注册并返回 SSO |
| `steps/_lite_engine.py` | curl_cffi、gRPC-web、Next.js Server Action、Turnstile 与 SSO 提取 |
| `steps/__init__.py` | lite 引擎导出 |
| `ui/` | 控制台项目规划与帮助 |
| `STEPS.md` | lite 流程步骤参考 |

## 配置与 Provider

| 能力 | Provider |
|---|---|
| 邮箱 | 功能级全局下拉（`allowed_email_ids=[]`）：`mailnest` / `tempmail` / `cloudflare_worker` / `xunmail` |
| Turnstile | `turnstile.yescaptcha` |
| 代理 | `socks5` |

项目参数位于 `projects.grok_register.*`，包括 `mail_timeout`、`turnstile_timeout` 与可选 `user_agent`。项目 schema 的 `task_ui.show_headless=false`，因此控制台隐藏无效的有头/无头选择；Provider 配置统一位于全局配置，不在项目内实现服务商逻辑。

### xAI 验证码格式

xAI 验证码为**字母数字混合格式**（如 `FPW-62T`、`RJ2-GX6`），非纯数字。邮箱 Provider 的验证码提取需支持该格式。

### gRPC-Web 响应解析

`_grpc_call` 同时从 HTTP 响应头和 body trailer 中读取 `grpc-status`；空响应体 + HTTP 200 时视为成功（Connect unary 模式兼容）。

**测试验证**：
- ✅ Web 控制台启动任务（`/projects/grok_register`），单账号 lite 协议流程
- ✅ 成功产出：SSO token（长度 ~152），格式 `email|sso`

## 产出

成功凭证为 SSO，按 `email|sso` 写入 `data/keys/grok_register/api_keys.txt`；控制台可继续使用共用导出能力。

## 成熟度验收

- **L1** ✅：单账号、并发 1，有 SSO 凭证
- **L2** ✅：同配置至少 5 个、并发 1，成功率至少 80%
- **L3** ✅：提高并发后批量成功率相对 L2 跌幅不超过 15 个百分点
- **L4** ❌：本项目是 HTTP lite 路径，按门禁最高认证到 L3；不能用它代替 L4 真实浏览器页面认证

Cloudflare 返回 `blocked_cf` 时先更换代理出口，不通过修改注册步骤绕过通道风控。

## 相关

- [步骤参考](STEPS.md)
- [项目 UI 规划](ui/schema.json)
- [共用 Web 控制台](../../web/README.md)
- [成熟度门禁](../../.trae/skills/project-maturity-gate/SKILL.md)
