# sms

## 职责

短信接码 Provider 总文件夹。对称于 `mailsys/`，供需要手机号验证的注册项目使用。

## 目录

| 子目录 | 说明 |
|--------|------|
| [`jichisms/`](jichisms/) | 疾驰短信 (jichisms.com) |
| [`haozhuma/`](haozhuma/) | 豪猪短信 (haozhuma.com) |

## 约定

```text
sms/<provider_id>/
  __init__.py
  provider.py      # SmsProvider 实现，导出 PROVIDER
```

- 配置键：`sms.<provider_id>`
- 接口：`get_phone` → `get_verify_code` → `release_phone`
- 项目只调用 `ctx.sms`，禁止内嵌接码实现

## 相关

- 基类：`core/base.py` → `SmsProvider`
- 归类规范：`.trae/skills/folder-layout/SKILL.md`
