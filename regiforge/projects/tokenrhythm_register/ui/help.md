# 基元律动 TokenRhythm

使用固定有头浏览器完成手机号注册、阿里云滑块、短信 OTP，并提取 `sk_tr_...` API Key。

- 短信选择 `jichisms`。TokenRhythm 在外部脚本对应的疾驰短信 SID 为 `138901`，请在全局“短信项目 SID”中按平台实际项目填写；系统不会写死或覆盖全局默认值。
- 验证码选择 `slider.aliyun`。可配置 yydsocr；未配置或识别失败时使用 OpenCV 模板匹配。
- 代理可选择 `none`、`http_proxy`、`socks5` 或 `clash`。
- 此流程依赖可见浏览器和滑块鼠标轨迹，不支持无头运行。
