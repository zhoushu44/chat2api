# proxy/http_proxy

## 职责

提供 HTTP/HTTPS 代理多行轮换，适用于 ChatGPT HTTP 注册模式（curl_cffi）以及其他需要 HTTP 代理的场景。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | HTTP/HTTPS 代理获取、格式规范化与轮换 |

## 使用方式

`server` 字段填写一行或多行 `http://` 或 `https://` 地址：

```text
http://user:pass@host1:port1
http://user:pass@host2:port2
https://host3:port3
```

**工作机制**：

- **轮换**：`acquire()` 每次返回下一个可用代理（内部索引循环）
- **失败标记**：`task_runner` 根据 `failure_class` 标记失败代理，自动跳过
- **格式处理**：自动 `trim()` 每行、过滤空行；无协议前缀时自动添加 `http://`

## 适用场景

- ChatGPT HTTP 模式（`register_mode=http`），curl_cffi 原生支持 HTTP 代理
- 任何需要 HTTP/HTTPS 代理的 API 请求

## 相关

- [代理系统](../README.md)
- [ChatGPT HTTP 引擎](../../projects/chatgpt_register/steps/_http_engine.py)