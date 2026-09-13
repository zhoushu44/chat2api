# ChatGPT2API（单镜像全功能版：Go 生图 + Python 注册引擎）

> **一个镜像 = Go 主服务（生图/API） + Python regiforge（自动注册） + Chrome**。
> 灰度走 `:3077`，老 Python 容器 `:3000` 不动。
> Docker 镜像：**`zhoushu1/chat2api`**（标签 `7.0` / `latest`），监听 `0.0.0.0:3077`。
> 进度总表见 [`进度.md`](进度.md)。

---

## 更新内容（7.0）

本版把「注册 → 入库 → 生图」全链路打通，并统一为单镜像交付。

### 1. 单镜像交付，本地/线上环境完全一致

注册引擎 `regiforge` 作为 `./regiforge` 子目录收进本仓库，与 `chatgpt2api` **打包进同一个镜像**。
容器内 Go 主服务监听 `0.0.0.0:3077`，regiforge 监听 `127.0.0.1:8787`（仅容器内），由 `supervisor` 统一拉起。

- 不再有容器间 DNS 问题：**彻底消除 `dial tcp: lookup regiforge: no such host`**
- 本地 `docker compose up -d --build` 与线上 `docker pull` 行为一致
- CI 只构建/推送这一个镜像（`Dockerfile.single`），本地无需任何 push

### 2. 连续失败自动熔断

注册页新增「连续失败自动停止」勾选项 + 失败轮次输入框：

| 字段 | 说明 | 默认 |
|---|---|---|
| `max_fail_enabled` | 是否启用熔断 | false |
| `max_fail_rounds` | 连续失败轮次上限（1–1000） | 10 |

某轮注册**全部失败**则计数 +1（有任何成功即清零）；达到上限后自动停止任务并关闭「自动注册」开关，避免无人值守时空转烧额度。

### 3. 停止即彻底停止

修复「暂停后仍有自动注册在运行」：`Stop` 会同时清掉 `auto_follow` 续跑标记，
轮询/补号流程均二次校验 `Enabled` 与 `AutoFollow`，停止后不再创建新任务。

### 4. 配置自动同步到注册引擎

用户在 chat2api 页面填写/环境变量配置的参数，会在创建注册任务前**自动推送到 RegiForge**（`PUT /api/config` 深度合并），无需两处重复配置：

| 配置 | 来源 | 作用 |
|---|---|---|
| `email.mailnest` | 页面邮箱 provider | 不推则报「MailNest 未配置 api_key」 |
| `proxy.wary` | `REGIFORGE_PROXY_API_URL` | 不推则静默直连，CN 出口被 OpenAI 403 |
| `export.chatgpt2api` | `REGIFORGE_EXPORT_*` | 不推则注册成功账号无法自动入库 |

### 5. 注册成功账号自动入库

注册成功的账号自动 `POST /api/accounts` 导入 chat2api 账号池（`POST /api/accounts` 已支持 `{tokens, accounts}` 批量格式，返回 `{added, skipped, refreshed, errors}`），导入账号默认标记为「正常」，可直接用于生图。

### 6. 生图出站代理

`chatgpt.com` 直连会被 CN 网络拒绝（`connection refused`），新增 `CHATGPT2API_PROXY` 环境变量注入 socks5 出口代理，生图链路可正常执行。

### 7. 实测结果

| 环节 | 结果 |
|---|---|
| 注册 | 成功 1/1，Session Token 已提取 |
| 入库 | `[auto-import] 新增 1`，账号状态「正常」 |
| 生图 | 返回 1 张图片（b64 约 2.8MB） |

**已知限制**：新账号 OAuth 流程会命中 `add-phone` 页面，仅拿到 Session Token、**未获取 refresh_token**（OpenAI 对新账号的风控）。生图可用，但 token 过期后无法自动刷新。

---

## 一、Docker 部署（推荐，最简）

镜像已由 GitHub Action 自动构建并推送到 Docker Hub：`zhoushu1/chat2api`。
容器内监听 `0.0.0.0:3077`，端口好记。

### 1. 拉取镜像

```bash
# 稳定版
docker pull zhoushu1/chat2api:7.0
# 最新版
docker pull zhoushu1/chat2api:latest
```

### 2. docker run 启动

```bash
docker run -d \
  --name chat2api \
  -p 3077:3077 \
  -v $(pwd)/data:/data \
  -e STORAGE_BACKEND=json \
  -e CHATGPT2API_AUTH_KEY=换成你的密钥 \
  --restart unless-stopped \
  zhoushu1/chat2api:latest
```

参数说明：

| 参数 | 作用 |
|---|---|
| `-p 3077:3077` | 宿主 3077 → 容器 3077（端口好记） |
| `-v $(pwd)/data:/data` | 配置与账号持久化到本地 `data/`（含 `config.json`、`accounts.json`） |
| `-e STORAGE_BACKEND=json` | 存储后端：json/sqlite/postgres/git/pebble |
| `-e CHATGPT2API_AUTH_KEY` | 调用 API 的 Bearer 鉴权密钥 |
| `--restart unless-stopped` | 开机自启、异常重启 |

Windows PowerShell 用 `$PWD` 替代 `$(pwd)`：

```powershell
docker run -d --name chat2api -p 3077:3077 -v ${PWD}/data:/data `
  -e STORAGE_BACKEND=json -e CHATGPT2API_AUTH_KEY=你的密钥 `
  --restart unless-stopped zhoushu1/chat2api:latest
```

> 完整环境变量（代理、自动入库等）见 [第四章](#四环境变量)。

### 3. 验证

```bash
curl http://127.0.0.1:3077/healthz
curl -H "Authorization: Bearer 你的密钥" http://127.0.0.1:3077/v1/models
# 生图（b64 真图）
curl -X POST http://127.0.0.1:3077/v1/images/generations \
  -H "Authorization: Bearer 你的密钥" -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-2","prompt":"a cat","n":1}'
```

> 生图需配置 `CHATGPT2API_PROXY`（socks5 非 CN 出口），否则报
> `all accounts failed: bootstrap: ... connect: connection refused`。

### 4. docker-compose 版（推荐生产用）

```yaml
services:
  chat2api:
    image: zhoushu1/chat2api:latest
    container_name: chat2api
    ports:
      - "3077:3077"
    volumes:
      - ./data:/data
    environment:
      - STORAGE_BACKEND=json
      - CHATGPT2API_AUTH_KEY=换成你的密钥
      # 生图出站代理（socks5 非 CN 出口）
      - CHATGPT2API_PROXY=socks5://代理地址:端口
      # 注册：代理池 + 自动入库
      - REGIFORGE_PROXY_API_URL=代理池API地址
      - REGIFORGE_PROXY_API_KEY=代理池密钥
      - REGIFORGE_EXPORT_BASE_URL=http://127.0.0.1:3077
      - REGIFORGE_EXPORT_ADMIN_PASSWORD=和上面鉴权密钥一致
    restart: unless-stopped
    shm_size: "1gb"
```

```bash
docker compose up -d        # 启动
docker compose logs -f      # 看日志，出现 "listening on :3077" 即起
docker compose down         # 停止
```

### 5. 准备 data/config.json

首次启动前在挂载的 `data/` 目录放 `config.json`：

```json
{
  "auth-key": "换成你的密钥",
  "proxy": "",
  "data_dir": "/data"
}
```

> 账号池放 `data/accounts.json`（`access_token` 等字段），首次可空数组 `[]`。

---

## 二、一键运行（源码构建单镜像）

```bash
# 一键构建并启动（首次构建需装 Chrome，耗时较久）
docker compose up -d --build

# 访问
open http://localhost:3077
```

镜像构成：

| 层 | 内容 |
|---|---|
| 构建阶段 | `golang:1.26-alpine` 编译出静态二进制 `/chatgpt2api-go` |
| 运行阶段 | `python:3.11-slim-bookworm` + Chrome + regiforge 依赖 + Go 二进制 |
| 进程管理 | `supervisor` 同时拉起 regiforge 与 chatgpt2api，任一退出自动重启 |
| 端口 | 仅对外暴露 `3077`（主服务）；regiforge 只在容器内 `127.0.0.1:8787` |
| 数据 | `./data` 挂载到 `/data`（含 config.json、accounts.json 等） |
| 构建文件 | `Dockerfile.single`（CI 与 compose 均使用它） |

不使用 compose 时，也可直接 `docker run`：

```bash
docker build -f Dockerfile.single -t chatgpt2api-all-in-one:local .
docker run -d --name chatgpt2api \
  -p 3077:3077 \
  -v "$PWD/data:/data" \
  -e CHATGPT2API_AUTH_KEY=你的密钥 \
  chatgpt2api-all-in-one:local
```

---

## 三、本地构建

```bash
# 纯本地（不含注册引擎，仅 Go 服务）
go build -o chatgpt2api-go ./cmd/server
./chatgpt2api-go -config config.json -addr :3077

# 前端产物需先构建并同步到 internal/api/web_dist
cd web-vue && npm install && npm run build   # 自动同步到 internal/api/web_dist
```

> ⚠️ 根目录 `Dockerfile` 为**纯 Go 轻量版**（无 regiforge/Chrome），仅用于最小化场景；
> CI 与生产请使用 **`Dockerfile.single`**。

## 四、环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `STORAGE_BACKEND` | 存储：json/sqlite/postgres/git/pebble | json |
| `CHATGPT2API_AUTH_KEY` | API Bearer 鉴权密钥 | — |
| `GIN_MODE` | release/debug | debug |
| `CHATGPT2API_PROXY` | **生图出站代理**（socks5/http） | — |
| `REGIFORGE_BASE_URL` | 注册服务地址（单镜像内为 127.0.0.1） | http://regiforge:8787 |
| `REGIFORGE_PROJECT_ID` | 注册项目 id | chatgpt_register |
| `REGIFORGE_PROXY_API_URL` | 注册用代理池 API（自动同步到 RegiForge） | — |
| `REGIFORGE_PROXY_API_KEY` | 代理池密钥 | — |
| `REGIFORGE_EXPORT_BASE_URL` | 自动入库地址（单镜像内 http://127.0.0.1:3077） | — |
| `REGIFORGE_EXPORT_ADMIN_PASSWORD` | 自动入库用的管理员密钥 | — |

pprof：`http://127.0.0.1:6060/debug/pprof/`

---

## 五、性能（mock 上游压测，非真实链路）

- 单图 P50 9.8s P95 11.2s（上游 8.5s + 本地 1s）
- 万级并发 P50 漂移 <5% QPS 1700+ 内存 9MB 无泄漏

```bash
go run ./cmd/m1demo
go run ./cmd/loadtest -n 10000 -latency 30ms -workers 2000
go run ./cmd/apistress
go test ./... -cover
```

---

## 六、CI 自动构建（GitHub Action）

push 到 `main` / `master` 自动构建并推送镜像到 Docker Hub：
**`zhoushu1/chat2api:7.0` + `:latest`**（同一个镜像打两个标签，由 Action 自动完成，**本地不执行任何推送**）。

构建文件为 `Dockerfile.single`（单镜像全功能版）。

**只需做一次**：在仓库 **Settings → Secrets and variables → Actions → New repository secret** 配两个 Secret：

| Secret 名 | 值 |
|---|---|
| `DOCKER_HUB_USERNAME` | Docker Hub 用户名（`zhoushu1`） |
| `DOCKER_HUB_TOKEN` | Docker Hub Access Token（Account Settings → Security → New Access Token，勾 read/write/push） |

配好后，每次 push `main`/`master` 即自动构建推送，**本地无需任何 docker push**。
手动触发：仓库 Actions → "Build & Push Docker Image" → Run workflow。
