# projects

## 职责

注册项目层。每个子目录是一个可下拉选择的注册站点/流程。

## 目录

| 子目录 | 说明 |
|--------|------|
| [`nvidia_build/`](nvidia_build/) | NVIDIA Build：`project.py` + `steps/stepNN_*.py` |
| [`grok_register/`](grok_register/) | xAI/Grok：lite HTTP、邮箱 OTP、Turnstile 与 SSO 产出流程 |
| [`chatgpt_register/`](chatgpt_register/) | ChatGPT/OpenAI：功能级邮箱下拉 + browser/http 双模式（http=Sentinel+Auth API），产出 Session Token |
| [`sensenova_register/`](sensenova_register/) | 商汤 SenseNova：OAuth2 PKCE HTTP + 疾驰短信接码，产出 API Key |
| [`tokenrhythm_register/`](tokenrhythm_register/) | 基元律动 TokenRhythm：有头浏览器 + 疾驰短信 + 阿里云滑块，产出 `sk_tr_` API Key |
| [`zcode_register/`](zcode_register/) | ZCode / Z.ai：OAuth 页直注册 + 功能级邮箱下拉（推荐 mailnest，依赖验证链接）+ 阿里云滑块（yydsocr+非线性映射），产出 accessToken |
| [`outlook_register/`](outlook_register/) | Microsoft Outlook / Hotmail：有头浏览器模拟真人填表 + 按压验证码 + 辅助邮箱绑定，产出 `email|password` |

## 标准结构（新项目必须遵守）

```text
projects/<project_id>/
├── project.py
├── steps/stepNN_*.py 或 steps/_lite_engine.py
├── ui/
│   ├── schema.json         # Web 规划（必写）
│   └── help.md
└── README.md
```

## 项目成熟度要求

每个项目独立按以下门禁升级：

```text
L1 成功（1×1 有凭证）
  → L2 稳定（同配置单并发至少 5 个，成功率 ≥80%）
  → L3 批量并发（提高 concurrency，较 L2 跌幅 ≤15 个百分点）
  → L4 Web 真实页面批量并发（必须从项目页点「启动任务」，正式页面主路径达到 L3）
```

某一级出现问题，必须读取 `data/debug/` 证据并修复或调整对应 Provider，完成同级复验后才能继续。禁止用一次成功、旁路脚本或 HTTP 捷径宣称 L4。升级操作见 [project-maturity-gate](../.trae/skills/project-maturity-gate/SKILL.md)。

## 新增项目

1. 建 `projects/<project_id>/`
2. 写 `project.py` → `PROJECT = ...`
3. 在 `steps/` 按 `stepNN_` 拆步骤
4. **写 `ui/schema.json`**：步骤清单、额外字段、能力约束、产出（共用壳自动读）
5. 只用 `ctx.captcha` / `ctx.email` / `ctx.sms` / `ctx.proxy`
6. 项目产出由共用 `TaskRunner` 统一写入全局 `ui.keys_output_dir`：控制台使用"选择文件夹"控件设置，不填文件名；留空为 `data/keys/<project_id>/api_keys.txt`，非空为 `<文件夹>/<project_id>_api_keys.txt`。行格式统一 `email|credential` 风格（见各项目 `output.line_format`），控制台预览与导入按钮读取同一文件。
7. 导出走全局 `export/*`（file / chatgpt2api / grok2api / sub2api），**不要**在项目 steps 里写导入逻辑；导入目标由 `ui/schema.json` 的 `import.exporter_id` 自动绑定（ChatGPT→chatgpt2api、Grok→grok2api），参数在 `web/ui/providers.json` 的 `when.exporter_id` 组。
8. 重启 Web；说「更新文档」同步 README

## 相关

- 归类规范：`.trae/skills/folder-layout/SKILL.md`
- 控制台：[`../web/`](../web/)
