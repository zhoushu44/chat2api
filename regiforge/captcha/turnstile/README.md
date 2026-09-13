# captcha/turnstile

## 职责

Cloudflare Turnstile 类型目录。

## 包含

| 子目录 | 说明 |
|--------|------|
| [`browser_manual/`](browser_manual/) | 等待站点浏览器正常签发结果；交互挑战由用户完成 |
| [`yescaptcha/`](yescaptcha/) | YesCaptcha API 自动解决 Turnstile |
| [`captcharun/`](captcharun/) | CaptchaRun API 自动解决 Turnstile |
| [`capsolver/`](capsolver/) | CapSolver API 自动解决 Turnstile |

## 约定

服务商实现放在 `turnstile/<vendor>/provider.py`，不得把 provider 单文件直接放在本目录。

## 相关

- 上级：[`../`](../)
