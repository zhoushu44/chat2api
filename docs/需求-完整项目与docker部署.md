# 完整项目 + 本地 Docker 部署服务器

> 要求（2026-09-09 用户定）：
>
> 1. **完整项目**：前端源码（web-vue）进本地项目 + git，不只产物（web_dist），源码也要在
> 2. **本地 build 好 docker 部署**：本机 build 前端 dist + 后端 Go，docker 镜像部署服务器

## 现状（2026-09-09 调研）

- Go 仓（chatgpt2api-go）：后端 Go + 前端产物 `internal/api/web_dist`（`//go:embed`）。**前端源码不在仓**（在服务器 `/opt/chatgpt2api/web-vue`）
- `web_dist` 是预编译产物（git `d4a79cf` 提交一次），之前本机 build 拷贝的
- 服务器 Node 16 + glibc 旧，build 不动 Vite 7（服务器不是前端 build 环境）

## 要求

### 1. 完整项目（前端源码进本地 + git）

- 把服务器 `/opt/chatgpt2api/web-vue` 源码拉到本地（如 `web-vue/`），git 提交
- 本地 + git 完整：**前端源码（.vue + package.json + vite.config）+ 后端 Go + 前端产物 web_dist 都在仓**
- 任何人 clone 仓能 build（不用去服务器拿前端源码）

### 2. 本地 build 好 docker 部署服务器

- 本机（Node 24）build web-vue → `dist` → 拷 `internal/api/web_dist`
- 本机 `go build`（embed 新 web_dist）
- 本机 `docker build` 镜像（Dockerfile），推/传服务器部署
- 服务器只跑 docker 容器，不 build

## 执行步骤

- [ ] 1\. SSH 拉服务器 `/opt/chatgpt2api/web-vue` 源码到本地 `web-vue/`（排除 node_modules/dist）
- [ ] 2\. `web-vue/` git 提交（前端源码进仓）
- [ ] 3\. 本机 `cd web-vue && npm install && npm run build` → `dist/`
- [ ] 4\. `dist/*` 拷到 `internal/api/web_dist/`（含改好的 Register.vue：warp 代理框 + 迈巢邮箱框）
- [ ] 5\. 本机 `go build`（embed 新 web_dist）
- [ ] 6\. 本机 `docker build` 镜像 + 部署服务器（docker-compose / Dockerfile）
- [ ] 7\. `:3077/#/register` 验证注册页两框（warp 代理框 + 迈巢邮箱框）显示 + 测试/保存

## 涉及

| 项                                   | 说明                                              |
| ----------------------------------- | ----------------------------------------------- |
| `web-vue/`（新）                       | 前端源码，从服务器拉，git 提交                               |
| `internal/api/web_dist/`            | build 产物，`//go:embed`，本机 build 后更新              |
| `Dockerfile` / `docker-compose.yml` | 本机 build docker 部署服务器                           |
| `Register.vue`                      | 改好：mailnest 邮箱选项 + warp 代理预设 + routes /register |

## 与注册两框需求关系

注册页**加 warp 代理框 + 迈巢邮箱框的改动（Register.vue + routes.ts）在 `web-vue/` 源码里改，本机 build 出 dist 进 web_dist，Go embed，docker 部署。前端源码进仓后，改 + build + 部署都在本地，不再依赖服务器 build。**
