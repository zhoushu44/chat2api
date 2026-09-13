# captcha/turnstile/browser_manual

## 职责

等待 Turnstile 在站点自己的浏览器页面中正常完成。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `turnstile.browser_manual` Provider |
| `__init__.py` | 导出 `PROVIDER` |

## 约定

本 Provider 不生成、注入或回放 challenge token；有交互挑战时由用户在有头浏览器中完成。

## 相关

- [Turnstile 类型](../README.md)
- [验证码层](../../README.md)
