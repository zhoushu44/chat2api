# sms/jichisms

## 职责

疾驰短信接码 Provider（jichisms.com）。取号 → 轮询验证码 → 释放号码。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `JichismsSmsProvider`，导出 `PROVIDER` |

## 配置

配置键：`sms.jichisms`

| 字段 | 说明 |
|------|------|
| `token` | 疾驰短信 fcToken |
| `sid` | 疾驰短信项目 ID |
| `ascription` | 卡号类型（1=移动, 2=联通） |
| `paragraph` | 号段筛选（可选） |
| `proxy` | 代理地址（由 TaskRunner 自动注入） |

环境变量：`JC_TOKEN`、`JC_SID`、`SMS_ASCRIPTION`、`SMS_PARAGRAPH`。

`sms.jichisms.sid` 是全局 Provider 配置，不按项目复制；SenseNova 与 TokenRhythm 在疾驰平台使用不同项目 ID 时，切换注册项目后需填写对应平台的 SID。

## 相关

- 基类：`core/base.py` → `SmsProvider`
- 使用项目：`projects/sensenova_register/`、`projects/tokenrhythm_register/`
