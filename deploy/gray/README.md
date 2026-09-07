# M1 灰度上线步骤（老 Python 容器不动）

## 1. 传仓到服务器

整仓（`chatgpt2api-go/`）传到服务器。私有仓：`deploy/gray/data/` 的
`config.json`（灰度 key）与单号 `accounts.json` 直接进仓，开箱即用；
`localtest-data/`、根目录账号 dumps、`*.exe`、`*.log` 仍被 `.gitignore` 隔离。
`deploy/gray/data/` 里只进仓 `config.example.json` 模板。

## 2. 服务器上准备灰度 data（示例）

```bash
mkdir -p /root/chatgpt2api-go-gray
cp -r deploy/gray/* /root/chatgpt2api-go-gray/
cd /root/chatgpt2api-go-gray
cp data/config.example.json data/config.json
# 按模板填 auth-key；proxy 留空（服务器出口干净，直连）
# accounts.json：放入测过的单号（Go 格式，与 localtest-data/accounts.json 同构）
```

## 3. 构建并启动（服务器上，Dockerfile 已在仓内）

```bash
GRAY_AUTH_KEY=实际灰度密钥 docker compose -f docker-compose.gray.yml build
GRAY_AUTH_KEY=实际灰度密钥 docker compose -f docker-compose.gray.yml up -d
docker logs -f chatgpt2api-go-gray   # 看到 listening on :3000 即起
```

## 4. 验证（老 :3000 不动，新 :3100）

```bash
curl http://127.0.0.1:3100/healthz
curl -H "Authorization: Bearer $GRAY_AUTH_KEY" http://127.0.0.1:3100/v1/models
# generations n=1 真图（b64 可解码）即 M1 灰度通过
```

## 5. 回滚

```bash
docker compose -f docker-compose.gray.yml down
```

老 Python 容器全程不动，回滚就是停掉灰度容器。
