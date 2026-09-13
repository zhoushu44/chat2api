# mailsys/cloudflare_worker

## 职责

通过 Cloudflare Email Routing + Worker 实时接收 NVIDIA 等验证邮件，提取验证码供注册流程读取。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `EmailProvider` 实现（生成邮箱 / 轮询验证码） |
| `worker.js` | Cloudflare Worker 源码（收信 + DO/KV） |
| `__init__.py` | 包标识 |

## 配置字段

`data/config.json` → `email.cloudflare_worker`：

Web 页面只显示一套全局共享配置；Grok、NVIDIA 等项目选择 `cloudflare_worker` 后复用相同的 API Base、API Key、域名和收件路径。旧 Worker/KV 字段仅作为运行时兼容兜底，不再按项目重复展示。

- `email_domain`：注册邮箱域名
- `cloudmail_api_base` / `cloudmail_api_key`：兼容原 `grok-register-cloudmail` 的 Cloud Mail 收件接口；配置后使用 `POST /api/public/emailList`
- `cloudmail_domains`：Cloud Mail 使用的域名（多个域名可用逗号分隔）
- `cloudmail_path_messages`：收件接口路径，默认 `/api/public/emailList`
- `worker_url` / `worker_token`：HTTP 读码端点
- `cf_api_token` / `cf_account_id` / `cf_kv_namespace`：KV 兜底（可选）

## NVIDIA OTP 解析

NVIDIA 验证邮件正文包含发件头、CSS 色值和收件地址等大量数字。Provider 会优先从
`verification code is` 或“验证码”附近提取六码验证码，支持 `123-456` 格式；只有未找到
明确验证码时才使用通用数字回退，避免把邮箱地址等无关数字填入 OTP 输入框。

## 流程简述

Cloud Mail 模式：邮件 → Cloud Mail Worker → `POST emailList` → 本地 `wait_code` 轮询。

旧 Worker/KV 模式：邮件 → Email Routing → Worker → Durable Object（即时）+ KV（备份）→ 本地 `wait_code` 轮询。

## 全局代理支持

**Cloudflare Worker API 请求会自动通过代理**（如果配置了 SOCKS5 代理）：

- `TaskRunner` 启动任务时自动将代理配置注入 `email_cfg["proxy"]`
- 统一流量出口，避免暴露真实 IP

配置方式：在 Web 控制台选择 `SOCKS5 代理` 并填写代理地址，所有 Cloudflare Worker API 请求自动通过该代理。

## 相关

- 上级：[`../`](../)
- [全局代理支持](../../core/README.md#全局代理支持)
