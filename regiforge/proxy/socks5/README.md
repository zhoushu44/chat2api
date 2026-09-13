# proxy/socks5

## 职责

提供统一 SOCKS5 Provider，支持固定单链接、多行轮换和代理池 API 动态获取。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | 配置解析、代理获取与格式规范化 |
| `forwarder.py` | 为带认证的上游 SOCKS5 建立本地转发 |
| `http_forwarder.py` | HTTP 代理转发 |

## 模式

### 1. 单/多行轮换模式

`server` 字段填写一行或多行 `socks5://host:port`：

```text
socks5://user:pass@host1:port1
socks5://user:pass@host2:port2
socks5://user:pass@host3:port3
```

**工作机制**：

- **轮换**：`acquire()` 每次返回下一个可用代理（内部索引循环）
- **失败标记**：`task_runner` 根据 `failure_class`（`proxy_dead`/`tls_error`/`exception`）标记失败代理
- **自动跳过**：轮换时跳过 `_failed_proxies` 集合中的代理
- **成功恢复**：代理成功后从失败集合移除
- **格式处理**：自动 `trim()` 每行、过滤空行、兼容 `socks5://` 和 `socks5h://`

### 2. 动态 API 模式

配置 `api_url`，从 HTTP 端点动态获取代理：

**配置字段**：
- `api_url`（必填）：代理 API 地址，如 `https://api.proxy.com/get`
- `api_key`（可选）：API 认证密钥，支持 `Bearer` 或 `X-API-Key` 头
- `timeout`（可选）：请求超时秒数，默认 10 秒
- `protocol`（可选）：协议类型，`socks5` 或 `socks5h`，默认 `socks5`
- `json_path`（可选）：JSON 提取路径，如 `data.proxy`

**支持格式**：
- **纯文本**：每行一个 `socks5://host:port` 或 `host:port`
- **JSON 对象**：自动提取 `proxy`、`ip`、`host` 等字段
- **JSON 数组**：`["host:port", ...]` 或 `[{"ip": "...", "port": ...}]`
- **HTML 表格**：`<table><tr><td>host</td><td>port</td></tr></table>`

**工作机制**：
- **随机选择**：从 API 返回的多个代理中随机选一个
- **智能解析**：自动探测常见 JSON 字段名
- **失败处理**：API 请求失败时抛出异常，任务会标记为失败

**优先级**：API 模式 > 手动配置模式 > 直连

## 相关

- [代理系统](../README.md)
- [SOCKS5 认证兼容](../../docs/SOCKS5_AUTH_COMPAT.md)
