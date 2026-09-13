# xAI / Grok 面板说明

## 注册模式

纯 HTTP 协议注册（lite 流程），无需浏览器、无需 Node.js：

1. **Bootstrap** — curl_cffi 访问注册页，自动提取 sitekey + next-action
2. **创建邮箱 + 发送验证码** — ctx.email 生成地址 + gRPC CreateEmailValidationCode
3. **等待 + 校验验证码** — ctx.email.wait_code + gRPC VerifyEmailValidationCode
4. **Turnstile + 建号** — ctx.captcha 解 Turnstile + Server Action create_account
5. **提取 SSO** — RSC body → set-cookie 链 → sso JWT

## 推荐组合

| 能力 | 推荐 | 说明 |
|------|------|------|
| 邮箱 | `tempmail` | TempMail.lol 临时邮箱，开箱即用 |
| 邮箱（备选） | `cloudflare_worker` / `xunmail` / `mailnest` | 已有配置可复用 |
| 验证码 | `turnstile.yescaptcha` | YesCaptcha API，支持 premium M1 |
| 验证码（备选） | `turnstile.captcharun` / `turnstile.capsolver` | 已有配置可复用 |
| 代理 | `socks5` | 输入 SOCKS5 链接；国内直连 x.ai 需代理 |

## 依赖

- **curl_cffi** — TLS 指纹传输（`pip install curl_cffi`）
- **YesCaptcha API Key** — 解 Turnstile
- **TempMail.lol API Key** — 临时邮箱（如选 tempmail）
- **代理** — 国内网络需配置 SOCKS5 代理（如 Clash 7897 端口）

## 产出

- 本地产出行格式：`email|sso`
- 导入 Grok2API Web：只上传 SSO Token，每行一个 Token
- 路径：`data/keys/grok_register/`
- 左侧「最近产出」与导出区读取同一文件

## 导出 / 导入账号池

控制台左侧 **导出 / 导入账号池**（与 NVIDIA、ChatGPT 同一块 UI）：

| 目标 | 参数要点 |
|------|----------|
| `file` | 文件夹路径 + 文件名，写出 `email\|sso` |
| `grok2api` | 根地址、管理员 JWT；当前自动导入 Grok Web，上传格式为每行一个 SSO Token |
| `sub2api` | 根地址、令牌、模板；凭据走 `$credential`（SSO 文本） |
