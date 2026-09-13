# sms/haozhuma

## 职责

豪猪短信接码 Provider（haozhuma.com）。登录获取 Token，取号、轮询验证码并释放号码。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `HaozhumaSmsProvider`，导出 `PROVIDER` |

## 配置

配置键：`sms.haozhuma`

| 字段 | 说明 |
|------|------|
| `account` | 豪猪 API 账号 |
| `password` | 豪猪 API 密码 |
| `base_url` | 服务地址，默认 `https://api.haozhuma.com` |
| `sid` | 豪猪平台项目 ID |
| `isp` / `Province` / `ascription` / `paragraph` | 可选取号筛选参数 |

## 接口

- 登录：`/sms/?api=login`
- 取号：`/sms/?api=getPhone`
- 收码：`/sms/?api=getMessage`
- 释放：`/sms/?api=cancelRecv`

## 相关

- 基类：`core/base.py` → `SmsProvider`
- 使用项目：`projects/sensenova_register/`、`projects/tokenrhythm_register/`
- API 文档：<https://www.showdoc.com.cn/haozhuma/11481322590171300>
