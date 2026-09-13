# projects/zcode_register/steps

## 职责

保存 ZCode / Z.ai 有头浏览器注册步骤。

## 包含

| 文件 | 说明 |
|------|------|
| `step01_open_oauth.py` | 打开 OAuth 授权页并切入注册表单；goto 用 `commit` + 3 次重试抗并发连接抖动 |
| `step02_fill_register.py` | 随机用户名 + 邮箱 + 密码，`_util.rand_*` 生成 |
| `step03_submit_captcha.py` | 点创建账号触发阿里云滑块 → `ctx.captcha.solve`（`slider.aliyun`）；识别「正在创建账户/验证通过」状态，通过后再次提交 |
| `step04_verify_email.py` | MailNest 轮询收验证邮件，`&amp;`→`&` 提取 verify 链接；打开后 45s 轮询等待「完成注册」表单（Vue SPA 渲染慢） |
| `step05_finalize_register.py` | 验证页填密码 + 确认密码，点完成注册 |
| `step06_extract_token.py` | 登录主界面后从 `localStorage.token` 提取 accessToken，并解码 `user_id` |
| `_util.py` | `rand_name()` / `rand_password()` / `captcha_visible()` 私有共享 |

## 约定

- 每步用 `dbg.run_step` 包装，失败自动落证据到 `data/debug/zcode_register/<task_id>/<index>/`。
- 验证码/邮箱/代理一律 `ctx.*`，不复制 Provider 实现。

## 相关

- [项目说明](../README.md)
- [注册调试规则](../../../.trae/rules/register-debug.md)
