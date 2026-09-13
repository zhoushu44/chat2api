# mailsys/xunmail

## 职责

通过寻邮（Xunmail）兼容协议，用 Outlook 四段式账号串取 OpenAI 等站点的邮箱验证码。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `EmailProvider` 实现（账号池 / Graph→OAuth2 取码） |
| `__init__.py` | 包标识 |

## 账号格式

每行一条：

```text
email----password----client_id----refresh_token
```

- 密码段仅兼容既有账号串格式，Provider **不会保存或发送**
- `client_id` + `refresh_token` 用于 Graph / OAuth2 取件

## 配置字段

`data/config.json` → `email.xunmail`（全局唯一，所有项目共用）：

| 字段 | 说明 |
|------|------|
| `api_address` | 寻邮 API 文档页、服务根或完整取件地址；默认 `https://www.xunmail.cn/api-doc` |
| `accounts` | 四段式账号池（多行文本或字符串列表） |

归一化后请求：

1. `POST {base}/api/graph/mail-all`（优先）
2. 失败回退 `POST {base}/api/oauth2/mail-all`
3. 同时查 `INBOX` 与 `Junk`，只取任务开始后的最新验证码

## 流程简述

`generate_address()` 从账号池弹出一条 → 页面发信 → `wait_code(email)` 轮询寻邮 → 返回 4–8 位 OTP。

## 如何扩展

新增 Outlook 账号：

1. 在寻邮平台注册并获取四段式信息
2. 在 `data/config.json` → `email.xunmail.accounts` 中添加一行
3. 格式：`email----password----client_id----refresh_token`

## 相关

- [邮箱系统](../README.md)
- [全局代理支持](../../core/README.md#全局代理支持)