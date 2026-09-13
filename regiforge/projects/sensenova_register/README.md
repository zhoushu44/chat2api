# projects/sensenova_register

## 职责

注册商汤 SenseNova：OAuth2 PKCE HTTP 流程 + 可选短信 Provider 接码，产出 API Key。

## 包含

| 文件/子目录 | 说明 |
|-------------|------|
| `project.py` | `PROJECT` 入口，编排 8 步 + 失败退避重试（频率限制至少等 30s） |
| `steps/_engine.py` | SenseNova HTTP 客户端与共享状态 |
| `steps/step01_oauth_challenge.py` | 获取 login_challenge |
| `steps/step02_acquire_phone.py` | 通过 ctx.sms 取号 |
| `steps/step03_send_sms.py` | 发送短信，按需调用滑块 Provider |
| `steps/step04_wait_sms.py` | 轮询短信验证码 |
| `steps/step05_verify_sms.py` | 校验验证码 |
| `steps/step06_register.py` | 创建账号 |
| `steps/step07_exchange_token.py` | 释放号码 + 交换 Token |
| `steps/step08_fetch_apikey.py` | 获取 API Key |
| `ui/schema.json` | Web 规划 |
| `ui/help.md` | 面板说明 |

## Provider 依赖

| 能力 | Provider |
|------|----------|
| 短信 | `jichisms` / `haozhuma`（控制台可选） |
| 验证码 | `slider.sensenova`（按需） |
| 代理 | `none` / `http_proxy` / `socks5` / `clash` |

## 产出

- `data/keys/sensenova_register/api_keys.txt`，行格式 `phone|api_key`
- 完整账号信息写入账号 JSONL

## 相关

- 短信 Provider：[`sms/jichisms/`](../../sms/jichisms/)
- 滑块 Provider：[`captcha/slider/sensenova/`](../../captcha/slider/sensenova/)
