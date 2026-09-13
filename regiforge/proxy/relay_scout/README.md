# proxy/relay_scout

## 职责

Relay Scout SOCKS5 代理池 Provider：通过 API 动态获取代理，支持粘性 session（同一会话多次 `acquire()` 拿回同一出口）。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | 调用 `GET {base_url}/api/v1/proxy`，取首行作为代理地址 |

## 使用方式

在 Web 控制台「代理」下拉选 `relay_scout`，填写 Relay Scout 配置组：

| 字段 | 必填 | 说明 |
|------|------|------|
| `base_url` | 是 | Relay Scout 服务地址（如 `http://192.6.121.16:8445`） |
| `api_key` | 是 | API Key（`?key=...`） |
| `project` | 否 | 项目 ID，默认 `default`（`?project=...`） |
| `session` | 否 | 粘性会话标识，相同 session 多次调用拿回同一出口（`?session=...`） |

## 工作机制

- **请求格式**：`GET {base_url}/api/v1/proxy?project=<p>&key=<k>&format=txt[&session=<s>]`，`format=txt` 表示响应为纯文本
- **响应解析**：取响应正文首行非空文本作为代理地址（`socks5://[user:pass@]host:port`），无前缀自动补 `socks5://`
- **粘性 session**：填了 `session` 时同一值多次 `acquire()` 会拿回同一出口 IP（适合 ChatGPT/Grok 这种按账号绑定身份的场景）；留空则按服务端默认轮换
- **失败处理**：API 4xx/5xx 或首行无法解析为 `host:port` 时抛 `RuntimeError`，由 `TaskRunner` 标记 `proxy_dead` 并切换到下一个代理

## 与 wary 的区别

| Provider | 协议 | 粘性机制 | 鉴权 |
|---------|------|---------|------|
| `relay_scout` | SOCKS5 | URL 传 `session` 参数 | URL `?key=` |
| `wary` | SOCKS5 | URL 含 `{sid}` 占位符，运行时替换为唯一会话 ID | URL `?key=` 或自定义 |

## 相关

- [代理系统](../README.md)
- [Wary Provider](../wary/)（同类 API 粘性代理池）
- [SOCKS5 Provider](../socks5/)（手填多行模式）
