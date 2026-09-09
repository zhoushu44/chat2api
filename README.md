# ChatGPT2API（Python 原版 ＋ Go 生图替换）

> Go 单二进制重写线上 Python v2.7.0 的生图等模块。灰度走 `:3077`，老 Python 容器 `:3000` 不动。
> Docker 镜像：**`zhoushu1/chat2api`**（标签 `4.0` / `latest`），监听 `0.0.0.0:3077`。
> 进度总表见 [`进度.md`](进度.md)。

---

## 一、Docker 部署（推荐，最简）

镜像已由 GitHub Action 自动构建并推送到 Docker Hub：`zhoushu1/chat2api`。
容器内监听 `0.0.0.0:3077`，端口好记。

### 1. 拉取镜像

```bash
# 稳定版
docker pull zhoushu1/chat2api:4.0
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

### 3. 验证

```bash
curl http://127.0.0.1:3077/healthz
curl -H "Authorization: Bearer 你的密钥" http://127.0.0.1:3077/v1/models
# 生图（b64 真图）
curl -X POST http://127.0.0.1:3077/v1/images/generations \
  -H "Authorization: Bearer 你的密钥" -H "Content-Type: application/json" \
  -d '{"model":"gpt-image-2","prompt":"a cat","n":1}'
```

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
    restart: unless-stopped
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

## 二、注册功能（M3 已对齐原版）

需要自动注册补号时，容器要 join `regiforge_default` 网络并注入 `REGIFORGE_*` 环境变量，才能连到 RegiForge 注册服务。docker-compose 完整版：

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
      - REGIFORGE_BASE_URL=http://regiforge:8787
      - REGIFORGE_PROJECT_ID=chatgpt_register
      - REGIFORGE_PROXY_ID=wary
      - REGIFORGE_EMAIL_ID=mailnest
    networks:
      - default
      - regiforge_default
    restart: unless-stopped

networks:
  regiforge_default:
    external: true
```

（`regiforge` 注册服务需在同 Docker 网络可见；无自动注册需求可忽略本节。）

---

## 三、本地构建

```bash
# 纯本地
go build -o chatgpt2api-go ./cmd/server
./chatgpt2api-go -config config.json -addr :3077

# 本地 Docker 构建
docker build -t zhoushu1/chat2api .
docker run -p 3077:3077 -v $(pwd)/data:/data zhoushu1/chat2api
```

## 四、环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `STORAGE_BACKEND` | 存储：json/sqlite/postgres/git/pebble | json |
| `CHATGPT2API_AUTH_KEY` | API Bearer 鉴权密钥 | — |
| `GIN_MODE` | release/debug | debug |
| `REGIFORGE_BASE_URL` | 注册服务地址 | http://regiforge:8787 |
| `REGIFORGE_PROJECT_ID` | 注册项目 id | chatgpt_register |

pprof：`http://127.0.0.1:6060/debug/pprof/`

---

## 五、性能（mock 上游压测，非真实链路）

- 单图 P50 9.8s P95 11.2s（上游 8.5s + 本地 1s）
- 万级并发 P50 漂移 <5% QPS 1700+ 内存 9MB 无泄漏
- 镜像 ≤50MB 启动 0.08s

```bash
go run ./cmd/m1demo
go run ./cmd/loadtest -n 10000 -latency 30ms -workers 2000
go run ./cmd/apistress
go test ./... -cover
```

---

## 六、CI 自动构建（GitHub Action）

push 到 `main` / `master` 自动构建并推送镜像到 Docker Hub：`zhoushu1/chat2api:4.0` + `:latest`。
**只需做一次**：在仓库 **Settings → Secrets and variables → Actions → New repository secret** 配两个 Secret：

| Secret 名 | 值 |
|---|---|
| `DOCKER_HUB_USERNAME` | Docker Hub 用户名（`zhoushu1`） |
| `DOCKER_HUB_TOKEN` | Docker Hub Access Token（Account Settings → Security → New Access Token，勾 read/write/push） |

配好后，每次 push `main`/`master` 即自动构建推送，**本地无需任何 docker push**。
手动触发：仓库 Actions → "Build & Push Docker Image" → Run workflow。
