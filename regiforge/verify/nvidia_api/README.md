# verify/nvidia_api

## 职责

使用 NVIDIA API 的 Bearer 认证请求验证 NVIDIA Key 是否可用。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | `NvidiaApiVerificationProvider` 实现 |
| `__init__.py` | 包标识 |

## 配置

`verify.nvidia_api.api_url` 默认为 `https://integrate.api.nvidia.com/v1/models`。

## 结果

返回 `usable`、状态及 HTTP 结果；HTTP 认证拒绝会标为 `rejected`。

## 相关

- [验证系统](../README.md)
