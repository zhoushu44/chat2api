# SOCKS5 代理认证兼容说明

## 问题

Playwright/Patchright 的 Chromium **不支持带认证的 SOCKS5 代理**。

如果你的代理地址包含用户名密码：
```
socks5://username:password@host:port
```

会遇到错误：
```
net::ERR_PROXY_CONNECTION_FAILED
```
或（带凭据被拒时）：
```
net::ERR_SOCKS_CONNECTION_FAILED
```

Playwright 的 `launch_persistent_context` 只支持：
- HTTP/HTTPS 代理认证（通过 `username`/`password` 字段）
- SOCKS5 免认证代理

## Provider 自动化兼容（推荐）

以下 Provider 在 `acquire()` 末尾**自动**检测 SOCKS5 凭据并启动本地 HTTP CONNECT 转发器，对调用方无感：

| Provider | 实现 | 备注 |
|----------|------|------|
| `socks5` | [`proxy/socks5/http_forwarder.py`](../../proxy/socks5/http_forwarder.py) | 多行轮换 + API 动态两种入口都会走 |
| `wary` | [`proxy/wary/provider.py:_with_auth_forwarder`](../../proxy/wary/provider.py) | 同款实现，WARP 粘性池场景 |
| `mihomo` | [`proxy/mihomo/provider.py:_with_auth_forwarder`](../../proxy/mihomo/provider.py) | 2026-08-19 补齐；`/api/connections` 返回的 socks 通常带凭据，不走转发器浏览器链路直接 `ERR_SOCKS_CONNECTION_FAILED` |
| `relay_scout` | [`proxy/relay_scout/`](../../proxy/relay_scout/provider.py) | 同款实现 |
| `clash` | 同款实现 | — |
| `http_proxy` | 不需要（HTTP 协议原生支持 `--proxy-server=http://...` + username/password） | — |

### 转发器行为

- 返回 `ProxyInfo.server = http://127.0.0.1:<随机端口>`（Chrome `--proxy-server=http://...` 拨号）
- `meta.upstream` 保留原始 `socks5://user:pass@host:port`
- 启动失败时回退 `socks5h://user:pass@host:port`（仅 `curl_cffi` / `requests` 兼容；浏览器链路仍会失败）

## 手动方案

如果遇到未覆盖的代理类型，可以选下面任一种：

### 方案 1：免认证 SOCKS5（最简单）

如果代理服务商支持，配置为免认证或 IP 白名单：
```
socks5://host:port
```

### 方案 2：HTTP 代理中转

HTTP 协议支持认证：
```
http://username:password@host:port
```

### 方案 3：本地 SOCKS5 工具转发

使用 Dante / ss-local 等把带认证的远程 SOCKS5 转成本地免认证：

```bash
socksify -f socks.conf -p 10800
```

然后用 `socks5://127.0.0.1:10800`。

### 方案 4：直连

`proxy_id=none`，本机网络直连目标网站。

## 当前支持情况

| 代理类型 | Playwright 支持 | Provider 是否自动处理 |
|---------|-----------------|---------------------|
| SOCKS5（免认证） | ✅ | n/a |
| SOCKS5（带认证） | ❌ | ✅ socks5 / wary / mihomo / relay_scout / clash |
| HTTP/HTTPS（带认证） | ✅ | n/a |

## 建议

1. **优先用 Provider 自动化**：除非 Provider 未覆盖，否则不需要手动配置转发。
2. **批量并发注意**：当前转发器**无 release hook**，每个 `acquire()` 都新开一个本地端口 + 后台线程。`total=5, concurrency=5` 会开 5 个端口；长时间运行累积有端口耗尽/线程泄漏风险。后续需补 release hook 或复用策略。
