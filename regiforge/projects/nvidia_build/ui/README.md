# projects/nvidia_build/ui

## 职责

本项目的 **Web 面板规划**。共用壳读取后渲染步骤、字段与说明。

## 包含

| 文件 | 说明 |
|------|------|
| `schema.json` | 步骤清单、项目字段、能力约束、产出文案 |
| `help.md` | 面板说明（含共用导出区用法） |

## 修改指引

- 改步骤展示 → 改 `schema.json` 的 `steps`（并与 `../steps/stepNN_*.py` 对齐）
- 加项目参数 → `fields` + `config_path`
- 限制可选邮箱/代理 → `allowed_email_ids` / `allowed_proxy_ids`
- 产出格式 → `output.line_format`（统一 `email|credential` 风格，供导出区解析）

## 约定

- 框架固定在 `web/static/index.html`，本目录只写项目差异。
- 邮箱/代理/验证码/导出凭据**不**在此声明；走全局 `web/ui/providers.json` 与 `export.*`。

## 相关

- 归类：`.trae/skills/folder-layout/SKILL.md`
- 共用壳：[`../../../web/`](../../../web/)
