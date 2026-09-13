# Debug Session: WARP Docker Tunnel

- Session ID: `warp-docker-tunnel`
- Status: [OPEN] — waiting for user confirmation
- Started: 2026-07-31
- Symptom: SOCKS5 端口可连接，但请求返回 SOCKS5 error 4；日志出现 CloudflareWARP nftables 规则失败。

## Hypotheses

1. 容器缺少 `/dev/net/tun` 或必要 capabilities，导致隧道接口未创建。**Rejected**
2. 容器 DNS/NTP/Cloudflare API 出站失败，导致首次注册未完成。**Rejected**
3. WARP 注册状态缺失或损坏，代理服务存在但没有可用上游。**Secondary symptom**
4. WARP 2026.6.880.0 与宿主机内核/nftables 组合不兼容。**Confirmed**

## Evidence

- 宿主机：CentOS 7，Linux `3.10.0-957.1.3.el7`，构建于 2018。
- 宿主机和容器均存在 `/dev/net/tun`。
- 容器可解析 `api.devices.cloudflare.com`。
- 容器直连 Cloudflare API 返回 HTTP 404，证明 DNS 和 HTTPS 出站正常。
- 原容器状态为 `unhealthy`。
- `warp-cli status` 返回 daemon connection refused。
- WARP 日志在 ConfiguringInitialFirewall 阶段失败：
  - `nft exited with code 1`
  - `oif "CloudflareWARP" ... No such file or directory`
  - `Firewall engine should be responding: ApplyError`
  - 主进程 panic。
- GOST 仍监听 1080，因此 curl 表现为 SOCKS5 error 4，而不是连接拒绝。

## Root Cause

`caomingjun/warp:latest` 中 Cloudflare WARP 2026.6.880.0 的 nftables 防火墙规则与该服务器的 CentOS 7 / Linux 3.10 环境不兼容，导致官方 WARP daemon 崩溃。DNS、Cloudflare API 和 TUN 都不是根因。

## Fix

- 停止原容器并改名为 `warp-official-failed`，未删除，保留回退。
- 部署 `ghcr.io/mon-ius/docker-warp-socks:v5`，使用 sing-box 用户态 WireGuard，避开官方 daemon 的 nftables 路径。
- 运行参数：`-p 1080:9091 -v warp-userspace-data:/data --restart=always`。

## Verification

### Pre-fix

- Container: `unhealthy`
- SOCKS5: error 4
- WARP trace: unavailable

### Post-fix (server local)

- Container: Up
- WireGuard handshake response received
- `warp=on`
- `ip=104.28.195.187`
- `loc=US`, `colo=LAX`

### Post-fix (remote Windows)

- Through `192.6.121.16:1080`
- `warp=on`
- Same exit IP `104.28.195.187`

## Documentation

Updated `C:\知识库\史蒂夫周\注册机\WARP Docker 部署教程.md` with root cause, tested deployment command, I/O, validation, mihomo integration, and security notes.

## Security

- Port 1080 is currently publicly exposed without authentication; restrict it at firewall level or bind to localhost.
- SSH password was disclosed in chat; rotate it immediately and migrate to key authentication.
