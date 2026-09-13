# projects/nvidia_build/steps

## 职责

按 **step 编号** 拆分的注册步骤。`project.py` 按序调用各 `stepNN_*.run`。

## 命名

- 公开步骤：`stepNN_描述.py`（两位数字）
- 私有共享：`_rpa.py`、`_flow.py`（下划线前缀，不注册）

## 步骤列表

| 文件 | 说明 |
|------|------|
| `step01_open_signin.py` | 打开 signin |
| `step02_accept_cookies.py` | Cookie |
| `step03_email_next.py` | 邮箱 → 注册表单；底层 `_flow.py` 使用语义回退选择器兼容登录弹窗属性变化 |
| `step06_input_password.py` | 密码 |
| `step07_confirm_password.py` | 确认密码 |
| `step08_check_agreement.py` | 协议 |
| `step09_solve_captcha.py` | 提取 sitekey（解题走 ctx.captcha） |
| `step10_inject_token.py` | 注入 token |
| `step11_create_account.py` | 创建账户；`_flow.py` 实现含 `/v1/error`（NVIDIA `SERVICE_UNAVAILABLE`）页面检测，避免假阳性 OK=true 让 step12 空等 |
| `step12_verify_email.py` | 邮箱验证码；`_flow.py` 实现含 `set_code_fetcher` / `set_mail_timeout` / `skip_codes` 透传；支持「验证码无效」一键重发 + 用 `skip_codes` 跳旧码重取一次 |
| `step13_fetch_apikey.py` | 取 API Key |

## 相关

- 编排入口：[`../project.py`](../project.py)
