# captcha/slider/sensenova

## 职责

SenseNova 图片滑块验证码 Provider。使用 OpenCV Canny 边缘检测 + 模板匹配定位滑块缺口。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `SensenovaSliderProvider`，导出 `PROVIDER` |

## 依赖

需要 `opencv-python-headless` 和 `numpy`（已在 `requirements.txt` 中）。

## 调用方式

项目通过 `ctx.captcha.solve()` 调用，传入 `session`、`proxies`、`iam_base` 等 kwargs。

## 相关

- 使用项目：`projects/sensenova_register/`
