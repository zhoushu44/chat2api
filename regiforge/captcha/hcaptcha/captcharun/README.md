# captcha/hcaptcha/captcharun

## 职责

CaptchaRun 服务商：通过 API 解 hCaptcha，返回 token。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `CaptchaRunHCaptchaProvider`，导出 `PROVIDER` |
| `__init__.py` | 导出 `PROVIDER` |

## 配置

配置键为 `captcha.hcaptcha.captcharun`：

```json
{
  "api_key": "",
  "api_url": "https://api.captcha-run.com/v2/tasks",
  "poll_interval": 3,
  "max_poll": 60
}
```

API Key 只保存在本地配置或 Web 配置表单中，不写入项目代码和文档。

## 相关

- [hCaptcha 类型](../README.md)
- [全局代理支持](../../../core/README.md#全局代理支持)
