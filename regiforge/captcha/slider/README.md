# captcha/slider

## 职责

图片滑块验证码类型。

## 目录

| 子目录 | 说明 |
|--------|------|
| [`aliyun/`](aliyun/) | 阿里云页面滑块：浏览器下载图片、yydsocr/OpenCV 识别缺口并**非线性换算**拖动距离（TokenRhythm / ZCode 共用） |
| [`sensenova/`](sensenova/) | SenseNova IAM 滑块：HTTP 获取图片、OpenCV 识别并提交坐标 |

`slider.aliyun` 依赖 Playwright `page` 和阿里云页面 DOM；`slider.sensenova` 依赖 SenseNova HTTP `session`/`iam_base` 并返回 `code_key`。两者输入、协议和用途不同，互不兼容。

## 相关

- 基类：`core/base.py` → `CaptchaProvider`
- 归类规范：`.trae/skills/folder-layout/SKILL.md`
