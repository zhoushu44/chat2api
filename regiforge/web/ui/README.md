# web/ui

## 职责

共用 Web 的 Provider 配置表单规划，不存放项目专属字段。

## 包含

| 文件 | 说明 |
|------|------|
| `providers.json` | 按 `when.captcha_id` / `email_id` / `sms_id` / `proxy_id` / `exporter_id` 显示全局配置组 |

## 约定

- 字段通过 `config_path` 映射 `data/config.json`；项目字段写入 `projects/<id>/ui/schema.json`。
- 当前库存包含 `slider.aliyun`、`slider.sensenova`、`sms.jichisms` 与 `sms.haozhuma`；`slider.sensenova` 无专属可编辑字段，仍由 Registry 与项目 schema 选择。
- 商汤 `sensenova_register` 与基元律动 `tokenrhythm_register` 的短信下拉均支持 `jichisms` / `haozhuma`；短信凭据仍按 Provider 全局共享配置。
- 同一 Provider 只保留一组全局配置，SMS 组使用 `when.sms_id`。
- MailNest UI 保留 `project_code` 作为兜底，不直接展示 `project_codes` 映射；后端仍兼容 `email.mailnest.project_codes.<project_id>`，用于不同项目选择不同编码。该兼容字段可在 JSON 配置中保留，不应因 UI 未展示而删除。
- 导入目标由项目 `import.exporter_id` 自动绑定；Exporter 配置同样在本文件按 `when.exporter_id` 声明。

## 环境变量

| 环境变量 | Provider | 说明 |
|----------|----------|------|
| `CAPTCHARUN_KEY` | CaptchaRun 各类型 | API Key |
| `YESCAPTCHA_API_KEY` / `YESCAPTCHA_KEY` | `turnstile.yescaptcha` | API Key |
| `YESCAPTCHA_API_URL` | `turnstile.yescaptcha` | API 地址 |
| `CAPSOLVER_KEY` | `turnstile.capsolver` | API Key |
| `TEMPMAIL_API_KEY` | `tempmail` | API Key |
| `MAILNEST_API_KEY` / `MAILNEST_BASE_URL` / `MAILNEST_PROJECT_CODE` | `mailnest` | MailNest 配置 |
| `CLOUDMAIL_API_BASE` / `CLOUDMAIL_API_KEY` / `CLOUDMAIL_DOMAIN` / `CLOUDMAIL_PATH_MESSAGES` | `cloudflare_worker` | CloudMail 配置 |
| `JC_TOKEN` / `JC_SID` / `SMS_ASCRIPTION` / `SMS_PARAGRAPH` | `jichisms` | 疾驰短信配置 |

## 相关

- [共用壳](../static/README.md)
- [配置加载](../../core/config_store.py)
