# captcha/hcaptcha

## 职责

hCaptcha 类型目录；其下每个子文件夹是一个服务商/解决方案。

## 包含

| 子目录 | 说明 |
|--------|------|
| [`captcharun/`](captcharun/) | CaptchaRun API 解题 |

## 如何扩展

新建 `captcha/hcaptcha/<vendor>/provider.py`，导出 `PROVIDER`，`type="hcaptcha"`。

## 相关

- 上级：[`../`](../)
