# 验证码“是否需要开墙”调试记录

状态：[OPEN]

## 症状
验证码不可用，需要确认 CaptchaRun API 是否必须通过代理访问，以及失败发生在创建任务还是轮询结果阶段。

## 假设
1. CaptchaRun API 直连被墙或网络不可达。
2. `sitekey` / `siteReferer` 参数不匹配，任务创建被服务商拒绝。
3. 任务创建成功，但轮询接口或代理出口不可用。
4. 服务商任务长期处理中或因额度/风控失败。

## 证据
- `https://api.yescaptcha.com` 直连返回 HTTP 200，响应为 YesCaptcha 欢迎信息。
- 同一地址经当前 SOCKS5 代理访问也返回 HTTP 200。
- `https://api.captcha-run.com/v2/tasks` 直连返回 HTTP 401（未带 Authorization），经当前 SOCKS5 代理同样返回 HTTP 401（未带 Authorization）。这证明两个出口均能到达服务，不是被墙或必须开墙。
- 当前任务配置为 `turnstile.yescaptcha`，不是 `turnstile.captcharun`；`data/config.json` 的最后选择也为 `turnstile.yescaptcha`。

## 结论
假设 1（直连被墙）和假设 3（代理出口不可达）暂不成立。当前不需要额外“开墙”；直连和 SOCKS5 都能访问验证码服务。若任务仍失败，下一步应读取实际任务日志中的 YesCaptcha `createTask` / `getTaskResult` 错误，重点检查 sitekey、websiteURL、API Key 额度/有效性及任务状态。
