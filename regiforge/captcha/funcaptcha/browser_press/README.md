# funcaptcha.browser_press — Microsoft 按压验证码

Outlook/Live 注册时的 `iframe#enforcementFrame` "验证质询" 按压验证码
（`aria-label="可访问性挑战"` / `aria-label="再次按下"`）。

- 无法通过 API 求解，必须在有头浏览器内模拟真人按压。
- 复用注册项目传入的 `Humanizer`（smooth_click 带偏移轨迹）。
- 按压 → 等待 `.draw` 脱离 → 轮询「让我们来保护你的帐户」/ `#EmailAddress`
  判定通过；识别「一些异常活动」判为 IP 风控。
- 配置：无（max_retries 由项目步骤透传，默认 3）。

调用方（项目步骤）示例：

```python
ok = await ctx.captcha.solve(
    sitekey="",
    page_url=page.url,
    page=page,
    humanizer=humanizer,
    max_retries=3,
)
```
