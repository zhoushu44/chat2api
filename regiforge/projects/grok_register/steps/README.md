# projects/grok_register/steps

## 职责

保存 xAI/Grok lite HTTP 注册引擎。

## 包含

| 文件 | 说明 |
|------|------|
| `_lite_engine.py` | curl_cffi 指纹传输、gRPC-web 编解码、Next.js Server Action、验证码与 SSO 提取 |
| `__init__.py` | 导出 lite 引擎模块 |

旧 browser 步骤、旧 http 引擎、协议客户端与 Castle runner 已删除；新增流程应继续复用 `ctx.email`、`ctx.proxy` 与 `ctx.captcha`。

## 相关

- [项目说明](../README.md)
- [步骤映射](../STEPS.md)
