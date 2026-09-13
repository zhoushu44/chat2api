# projects/tokenrhythm_register/ui

## 职责

TokenRhythm 项目的 Web 控制台规划。

## 包含

| 文件 | 说明 |
|------|------|
| `schema.json` | 项目字段、9 步流程、Provider 白名单与 `phone|api_key` 产出 |
| `help.md` | 面板操作与配置说明 |

## 约定

- 仅允许 `slider.aliyun` 与 `jichisms`。
- 注册流程固定使用有头浏览器，控制台隐藏 `headless`。
- 项目参数写入 `projects.tokenrhythm_register.*`，Provider 凭据保持全局配置。

## 相关

- [项目入口](../README.md)
- 共用壳：`web/static/index.html`
