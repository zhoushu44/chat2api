# projects/tokenrhythm_register/steps

## 职责

TokenRhythm 有头浏览器注册的 9 步流程，由 `project.py` 通过 `RegisterDebug.run_step()` 执行。

## 包含

| 文件 | 说明 |
|------|------|
| `_state.py` | `RegistrationState` 共享状态 |
| `step01_acquire_phone.py` | 通过 `ctx.sms` 获取手机号 |
| `step02_open_register.py` | 打开注册页并填写手机号 |
| `step03_send_code.py` | 请求发送短信验证码 |
| `step04_solve_captcha.py` | 通过 `ctx.captcha` 完成阿里云滑块 |
| `step05_wait_sms.py` | 通过 `ctx.sms` 轮询 OTP |
| `step06_submit_code.py` | 填写短信 OTP |
| `step07_accept_agreement.py` | 同意用户协议 |
| `step08_submit_register.py` | 提交注册并等待成功页 |
| `step09_fetch_apikey.py` | 提取 `sk_tr_` API Key |

## 相关

- [项目入口](../README.md)
- 调试规则：`.trae/rules/register-debug.md`
