# projects/tokenrhythm_register

## 职责

以有头浏览器完成基元律动 TokenRhythm 手机号注册，支持选择短信 Provider，处理阿里云滑块并产出 `sk_tr_` API Key。

## 包含

| 文件/子目录 | 说明 |
|-------------|------|
| `project.py` | `PROJECT` 入口，使用 `RegisterDebug` 编排 9 步 |
| `steps/` | 取号、注册、滑块、短信 OTP 与提取 Key 的编号步骤 |
| `ui/schema.json` | Web 字段、Provider 白名单、步骤与产出规划 |
| `ui/help.md` | 控制台使用说明 |

## Provider 依赖

| 能力 | Provider |
|------|----------|
| 短信 | `jichisms` / `haozhuma`（控制台可选） |
| 验证码 | `slider.aliyun` |
| 代理 | `none` / `http_proxy` / `socks5` / `clash` |

`slider.aliyun` 需要 Playwright `page`，通过浏览器上下文下载验证码图片；优先调用可选 yydsocr，失败或未配置时回退本地 OpenCV。

## 产出

- `data/keys/tokenrhythm_register/api_keys.txt`
- 行格式：`phone|sk_tr_...`

## 相关

- [步骤说明](steps/README.md)
- [UI 规划](ui/README.md)
- [疾驰短信](../../sms/jichisms/README.md)
- [阿里云滑块](../../captcha/slider/aliyun/README.md)
