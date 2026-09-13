# config

## 职责

存放不含真实密钥、可提交到版本库的配置模板。

## 包含

| 文件 | 说明 |
|------|------|
| `settings.example.json` | 可提交的完整默认结构模板，不存放用户运行配置 |

## 配置范围

- Captcha：`captcha.slider.aliyun`、`captcha.slider.sensenova` 及 hCaptcha、Cloudflare、Turnstile Provider。
- SMS：`sms.jichisms`，其中 `sid` 为目标平台项目 ID。
- 项目：`projects.nvidia_build`、`grok_register`、`chatgpt_register`、`sensenova_register`、`tokenrhythm_register`。
- 验证/导出：`verify.nvidia_api`、`export.file`、`sub2api`、`grok2api`、`chatgpt2api`。
- UI：最近选择项与 `ui.keys_output_dir`；可包含 `last_sms_id`。

运行时真实配置位于 `data/config.json`，由 `core/config_store.py` 与内置默认值深度合并；同步模板不会覆盖用户文件。`settings.example.json` 仅使用空字符串或非敏感默认值，可安全提交。

`ui.keys_output_dir` 留空时写 `data/keys/<project_id>/api_keys.txt`，非空时写 `<文件夹>/<project_id>_api_keys.txt`。

## 相关

- [配置读写](../core/config_store.py)
- [Provider UI](../web/ui/README.md)
