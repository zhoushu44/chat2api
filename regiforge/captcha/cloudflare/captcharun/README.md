# captcha/cloudflare/captcharun

## 职责

CaptchaRun 服务商：通过 API 解 CloudFlare5s 盾，返回 `cf_clearance` Cookie 及 UA。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `CaptchaRunCloudflareProvider`，导出 `PROVIDER` |
| `__init__.py` | 导出 `PROVIDER` |

## 配置

`data/config.json` → `captcha.cloudflare.captcharun`：

- `api_key` / `api_url` / `poll_interval` / `max_poll`

> 解题时需传入代理信息（`proxy_host` / `proxy_port` / `proxy_login` / `proxy_password`），请确保当前项目已配置代理。

## 相关

- 上级：[`../`](../)
