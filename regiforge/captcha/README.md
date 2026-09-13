# captcha

## 职责

验证码总文件夹。层级：**类型 → 服务商文件夹 → provider.py**。

## 目录

| 路径 | 说明 |
|------|------|
| [`cloudflare/captcharun/`](cloudflare/captcharun/) | CloudFlare5s + CaptchaRun 服务商 |
| [`cloudflare/flaresolverr/`](cloudflare/flaresolverr/) | FlareSolverr 远程 Cloudflare 挑战处理服务 |
| [`hcaptcha/captcharun/`](hcaptcha/captcharun/) | hCaptcha + CaptchaRun 服务商 |
| [`turnstile/browser_manual/`](turnstile/browser_manual/) | 在站点浏览器中正常完成 Turnstile |
| [`turnstile/yescaptcha/`](turnstile/yescaptcha/) | YesCaptcha Turnstile |
| [`turnstile/captcharun/`](turnstile/captcharun/) | CaptchaRun Turnstile |
| [`turnstile/capsolver/`](turnstile/capsolver/) | CapSolver Turnstile |
| [`slider/aliyun/`](slider/aliyun/) | 阿里云页面图片滑块（浏览器拖动，yydsocr/OpenCV 识别） |
| [`slider/sensenova/`](slider/sensenova/) | SenseNova IAM 图片滑块（HTTP 接口 + OpenCV） |

## 约定

```text
captcha/<type>/<vendor>/
  __init__.py      # 导出 PROVIDER
  provider.py      # CaptchaProvider 实现
```

- `PROVIDER.type` = 类型目录名
- `PROVIDER.id` = 服务商目录名
- 注册 key：`{type}.{id}`（如 `hcaptcha.captcharun`）

## 相关

- 归类规范：`.trae/skills/folder-layout/SKILL.md`
- 基类：`base.py` / `core/base.py`
