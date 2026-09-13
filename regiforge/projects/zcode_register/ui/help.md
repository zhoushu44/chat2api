# Zcode / Z.ai 注册

通过 Z.ai 官方 OAuth 授权链接（zcode 桌面端登录入口）注册账号：

1. 打开 `https://chat.z.ai/auth?response_type=code&client_id=...` 授权页
2. 点「注册」切入注册表单，填写随机用户名 / 临时邮箱 / 密码
3. 点「创建账号」触发阿里云滑块 —— 由 `captcha.slider.aliyun` 处理：
   - yydsOCR 识别缺口（需在 Provider 配置填 secret_key / api_url）
   - 非线性映射 `drag_distance` 换算真实拖动距离（与基元 tokenrhythm 同款系数）
4. 滑块通过后再次点「创建账号」提交，进入「验证您的邮箱」页
5. MailNest 轮询收取验证邮件，提取 `verify_email` 链接并打开
6. 在「完成注册」页设置密码，点「完成注册」，登录 Z.ai 主界面
7. 从 `localStorage` 提取 token 作为 accessToken 凭证

## 依赖 Provider

| 能力 | Provider | 说明 |
|------|----------|------|
| 邮箱 | `email.mailnest` | product_code = `z-ai001`（已在 mailnest 默认表注册） |
| 验证码 | `captcha.slider.aliyun` | yydsOCR（secret_key/api_url/type_id=20040）+ OpenCV 兜底；默认走非线性换算 |
| 代理 | `proxy.socks5` 等 | 可选，直连也可注册 |

## 成功凭证

`accessToken`（z.ai 登录态 localStorage `token`，JWT）。产出写入 `data/keys/zcode_register/api_keys.txt`。
