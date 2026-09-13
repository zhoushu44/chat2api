# projects/sensenova_register/steps

## 职责

商汤 SenseNova 注册的 8 步编排。每步一个 `stepNN_*.py`，由 `project.py` 通过 `RegisterDebug.run_step()` 逐步执行。

## 包含

| 文件 | 说明 |
|------|------|
| `_engine.py` | SenseNova HTTP 客户端与 `RegistrationState` 共享状态 |
| `step01_oauth_challenge.py` | 获取 login_challenge |
| `step02_acquire_phone.py` | 通过 ctx.sms 取号 |
| `step03_send_sms.py` | 发送短信，按需调用滑块 Provider |
| `step04_wait_sms.py` | 轮询短信验证码 |
| `step05_verify_sms.py` | 校验验证码 |
| `step06_register.py` | 创建账号 |
| `step07_exchange_token.py` | 释放号码 + 交换 Token |
| `step08_fetch_apikey.py` | 获取 API Key |

## 相关

- [项目入口](../README.md)
- 调试规则：`.trae/rules/register-debug.md`
