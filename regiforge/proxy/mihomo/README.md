# proxy/mihomo

## 职责

通过 mihomo（Mihomo-Relay-WebUI）服务器 7892 端口的 API 拉取当前对外连接入口（SOCKS5/HTTP），返回可用的代理地址。适用于模式 E「API 提取」等由 mihomo 服务端自动切换上游代理的场景。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | mihomo API 调用、入口拉取、协议选择与 **SOCKS5 认证自动 HTTP 转发** |

## 使用方式

### 配置字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `api_base` | 是 | WebUI API 根地址，如 `http://192.6.121.16:7892` |
| `api_key` | 是 | WebUI API Key |
| `protocol` | 否 | 返回入口协议：`socks5`（默认）或 `http` |
| `rotate` | 否 | 每次 `acquire()` 是否先 `POST /api/rotate` 换新出口 IP（默认 `false`） |

### 工作机制

1. `GET /api/connections?key=KEY` 拉取当前入口
   - SOCKS5：`socks5://user:pass@host:7890`
   - HTTP：`http://user:pass@host:7891`
2. 按 `protocol` 选取对应入口，校验 `enabled` 后返回 `ProxyInfo`
3. 若配置 `rotate=true`，则每次 acquire 先 `POST /api/rotate` 刷新出口

> 模式 E 下，mihomo 服务端每 2 分钟自动检测、过期才提取上游代理，通常无需每账号轮换；`rotate` 默认关闭。

## SOCKS5 凭据自动兼容（修复「打不开网页」）

**症状**：用 `proxy_id=mihomo` 启动浏览器任务，step01 122s 后超时停在 `chrome-error://chromewebdata/`，错误码 `ERR_SOCKS_CONNECTION_FAILED`。

**根因**：mihomo 7890 通常启用 RFC1929 用户名密码认证（`sockstest:socks-pass@1`）。Playwright/Patchright 的 Chromium 通过 `--proxy-server=socks5://host:port` 拨号时 **不携带凭据**（Chrome 不支持 SOCKS5 认证），服务器认证拒绝 → `ERR_SOCKS_CONNECTION_FAILED`。

**修复**：[`provider.py:_with_auth_forwarder`](provider.py) 在 `acquire()` 末尾检测到带凭据的 SOCKS5 入口时：

1. 启动本地 HTTP CONNECT 转发器 `Socks5HttpForwarder`（[proxy/socks5/http_forwarder.py](../socks5/http_forwarder.py)），监听 `http://127.0.0.1:<随机端口>`
2. Chrome 连本地 HTTP 端口，转发器内部用 `socks.SOCKS5` 带凭据连上游 `socks5://user:pass@host:7890`
3. 返回的 `ProxyInfo.server` 由 `socks5://user:pass@host:port` 变为 `http://127.0.0.1:<port>`，`meta.upstream` 保留原 socks URL 便于追溯
4. 转发器启动失败时回退 `socks5h://user:pass@host:port`（`curl_cffi` / `requests` 兼容；浏览器链路仍 `ERR_SOCKS_CONNECTION_FAILED`）

**复现验证**：`test` 任务 `f5873b614b1f`，代理行从 `代理: socks5://sockstest:socks-pass%401@192.6.121.16:7890` 变为 `代理: http://127.0.0.1:6322`，step01_open_create 用时从 122s 超时 → 28.9s 成功到 `signup.live.com`。

**遗留**：

- HTTP 转发器**没有 release hook**：每个 `acquire()` 都会开一个本地端口 + 后台线程，任务结束不主动停，**批量并发开 N 个会端口爆**。
- `proxy.mihomo.rotate=true` 时每次 acquire 都会重开 forwarder（同样有端口消耗）。

## 相关

- [代理系统](../README.md)
- [SOCKS5 认证兼容说明](../../docs/SOCKS5_AUTH_COMPAT.md)
- [mihomo WebUI 部署文档](../../docs/anti-detect/ip/mihomo%20webui.md)
- [Socks5HttpForwarder 实现](../socks5/http_forwarder.py)
- [Wary Provider（SOCKS5 认证自动转发的同款实现）](../wary/README.md)
