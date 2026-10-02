# 服务器修复记录：旧公网 IP 硬编码导致 sub2api 崩溃循环

> 修复时间：2026-10-03 00:11 (CST)｜服务器：195.72.185.32

## 一、问题

`sub2api` 容器每 2 分钟崩溃重启一次，累计 **5758 次**，导致 `token.86969678.xyz` 对外入口间歇性不可用。

## 二、根因

**服务器更换过公网 IP**：旧 IP `192.6.121.16` → 现 IP `195.72.185.32`。

旧 IP 被硬编码在多个配置里，指向的其实是**本机服务**（当时从公网绕回本机可用，换 IP 后全部失效）：

| 配置文件 | 字段 | 原值 | 实际意图 |
|---|---|---|---|
| sub2api `/app/data/config.yaml` | `database.host:port` | `192.6.121.16:35432` | 本机 Postgres 容器 |
| 同上 | `redis.host` | `192.6.121.16:6379` | 本机 Redis 容器 |
| `/opt/chatgpt2api/config.json` | `base_url`（2 处） | `http://192.6.121.16:3000` | 图片结果公网前缀 |
| `/opt/regiforge/web/ui/providers.json` | 多处默认值 | `http://192.6.121.16:*` | 本机 FlareSolverr/代理池等 |

**额外发现**：sub2api 在 `bridge` 网络，Postgres 在 `baota_net` 网络（172.18.0.0/16），
两网默认不通；且宿主机 firewalld 末尾 `REJECT all` 拦截了 docker 网段访问宿主端口，
所以「改回 127.0.0.1 / 宿主内网 IP」都不可行。

## 三、修复动作

### P0 · sub2api 数据库/Redis 连接

```bash
# 1) 备份（容器内 + 宿主机）
docker exec sub2api cp /app/data/config.yaml /app/data/config.yaml.bak-<ts>
docker cp sub2api:/app/data/config.yaml /root/sub2api-backup/config.yaml.orig-<ts>

# 2) 把 sub2api 接入 Postgres 所在网络
docker network connect baota_net sub2api

# 3) 配置改为容器名互联（走 docker 内网 DNS，不受宿主 IP 变化影响）
#    database.host: postgresql_cdTF   port: 5432
#    redis.host:    redis_yrwS        port: 6379
docker cp /tmp/cfg.new sub2api:/app/data/config.yaml

# 4) 重启验证
docker restart sub2api
```

### P1 · chat2api 图片前缀

`base_url` 是**图片结果的公网访问前缀**（`support.py` 中兜底用请求 Host），
不能设为 `127.0.0.1`（外部用户打不开），改为当前公网 IP：

```
base_url: http://195.72.185.32:3000   （顶层 + basic 两处）
```

**坑**：`sed -i` 会创建新文件并 rename，而 Docker bind mount 绑定 **inode**，
导致宿主改了但容器读的还是旧文件（报 `Device or resource busy`）。
正确做法是原地覆盖：

```bash
docker exec chatgpt2api sh -c \
  'sed "s|http://[0-9.]*:3000|http://195.72.185.32:3000|g" /app/config.json > /tmp/c.json \
   && cat /tmp/c.json > /app/config.json && rm -f /tmp/c.json'
```

## 四、修复结果

| 指标 | 修复前 | 修复后 |
|---|---|---|
| sub2api RestartCount | 5758 且持续增长 | **0**（重启后清零，持续保持） |
| 修复后错误数（7 分钟） | 每 2 分钟 1 次崩溃 | **0** |
| `token.86969678.xyz` | 间歇 502/超时 | **HTTP 200 (0.2s)** |
| sub2api 本地 8080 | 崩溃循环 | **HTTP 200 (2ms)** |
| chat2api :3000 | 正常 | **HTTP 200 (10ms)** |
| chat2api-13 :3077 | 正常 | **HTTP 200 (6ms)** |

## 五、回滚

```bash
# sub2api
docker cp /root/sub2api-backup/config.yaml.orig-<ts> sub2api:/app/data/config.yaml
docker restart sub2api

# chatgpt2api
cp /opt/chatgpt2api/config.json.bak-<ts> /opt/chatgpt2api/config.json   # 注意保持 inode 原地覆盖
docker restart chatgpt2api
```

## 六、遗留（P2，未处理）

`/opt/regiforge/web/ui/providers.json`（及 `/opt/regiforge/app/web/ui/providers.json`）
各有 7 处旧 IP，均为**表单默认值/占位符**：

- `:8191` FlareSolverr、`:4433` 代理池 API —— 当前**无对应容器**（未部署）
- `:8445` relay-scout、`:7892` mihomo-web —— **容器在跑**，默认值失效会导致一键填入错误地址

影响面：仅 UI 默认值，不影响已在页面保存过的配置。需要时把这 7 处替换为
`127.0.0.1`（regiforge 与这些服务同宿主）或对应容器名即可。

## 七、经验

1. **不要硬编码公网 IP 指向本机服务** —— 换 IP 即全线失效。容器间用**容器名**（docker DNS），
   容器访问宿主用 `host.docker.internal`（需 `--add-host`）或宿主 bridge 网关。
2. **该服务器是宝塔环境**，业务容器分散在 `bridge` 与 `baota_net` 两个网络，
   跨网络访问必须先 `docker network connect`。
3. **改 bind mount 内的文件不要用 `sed -i`**（换 inode 导致容器看不到），用原地覆盖。
4. `192.6.121.16` 仍出现在前端构建产物里（注册页 warp 代理默认值 `socks5://192.6.121.16:11010`），
   属于同类遗留，需要时一并处理。
