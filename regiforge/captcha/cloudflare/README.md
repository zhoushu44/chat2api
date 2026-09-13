# captcha/cloudflare

## 职责

CloudFlare5s 验证码类型的 Provider 目录；其下每个子文件夹是一个服务商/解决方案。

## 包含

| 子目录 | 说明 |
|--------|------|
| [`captcharun/`](captcharun/) | CaptchaRun CloudFlare5s 解题 |

## 如何扩展

新建 `captcha/cloudflare/<vendor>/provider.py`，导出 `PROVIDER`，`type="cloudflare"`。

## 相关

- 上级：[`../`](../)
