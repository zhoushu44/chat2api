# captcha/slider/aliyun

## 职责

处理阿里云图片滑块，注册 ID 为 `slider.aliyun`。TokenRhythm 与 ZCode 注册共用（与基元同款算法）。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | 展开弹层、下载背景图和拼图、yydsocr/OpenCV 识别缺口、非线性换算拖动距离并在 Playwright 页面模拟拖动 |

## 配置

配置键：`captcha.slider.aliyun`。

| 字段 | 说明 |
|------|------|
| `api_url` | 可选 yydsocr 识别接口 |
| `secret_key` | 可选 yydsocr 密钥 |
| `type_id` | yydsocr 类型，默认 `20040` |
| `max_retries` | 滑块最大重试次数，默认 `3` |

验证码图片由 Playwright `page.context.request` 沿当前浏览器网络路径下载；缺口识别优先走 yydsocr，未配置或失败时回退本地 OpenCV。

### 非线性映射（拖动距离换算）

识别出缺口横向偏移 `puzzle_x` 后，用一元二次公式换算真实拖动距离：

```text
drag_distance = int((-b + sqrt(b² + 4·a·puzzle_x)) / (2·a))
a = 0.003550, b = 0.076971
```

与「基元」/TokenRhythm 同款算法，不能用原始缺口像素直拖。

### 弹层交互

部分站点先出现「点击开始验证」入口按钮，需点击展开弹层；弹层展开（`#aliyunCaptcha-window-float` 非 `window-hidden`）后停止重复点击入口，避免把弹层收起导致死循环。

本 Provider 面向阿里云页面 DOM 与浏览器拖动；`slider.sensenova` 面向 SenseNova IAM HTTP 接口并返回 `code_key`，两者协议、输入和用途不同，互不兼容。

## 相关

- [滑块类型](../README.md)
- [TokenRhythm 项目](../../../projects/tokenrhythm_register/README.md)
- [ZCode 项目](../../../projects/zcode_register/README.md)
