# Changelog

本文件记录 Go 版 `chatgpt2api` 的版本变更。
版本号同时维护在三处，**必须保持一致**：git tag / `VERSION` / `.github/workflows/docker-publish.yml` 的 `TAG_MAJOR`。

## 24.5

**类型**：首页账号分类统计

- 首页账号卡片更新为：账号总数、正常账号、限流账号、待重登、生图失效、已禁用、剩余额度。
- `/api/dashboard` 新增 `need_relogin`、`image_blocked` 独立计数，不再混入禁用或异常。
- 与账号页的状态分类保持一致。

## 24.4

**类型**：面板登录修复

- `/auth/login` 支持页面提交的 `{"password":"..."}`，与 Bearer / X-Api-Key 共用主密钥鉴权。
- 修复配置正确的主密钥在页面上始终返回「密钥无效或已失效」的问题。
- 新增密码表单登录与错误密钥拒绝测试。

## 24.3

**类型**：注册服务与生图服务恢复链路打通

- RegiForge 导出器逐账号透传 `password`、`totp_secret`、`session_token`，仅在非空时发送。
- Go 账号模型、持久化和调度池保留恢复凭据，AT 失效后可执行密码 + TOTP 协议登录恢复。
- 账号列表只返回 `has_password`、`has_totp`、`recoverable`，不回显密码/TOTP/session 明文。
- 修正导出测试为当前单账号 POST 接口，并补充 Go 导入、持久化与脱敏测试。

## 24.2

**类型**：生图根因修复 + 账号恢复/清理 + 面板分类

- **生图根因修复**
  - 参考图 ID 贯穿轮询和 URL 解析全程排除，避免失效账号把用户参考图当作生成结果返回
  - 排除参考图后无新图时报 `no_image_generated`，不再静默成功
  - 有文本回复但无图片指针时判定 `upstream_text_reply`，不再吞成统一 `upstream_error`
- **账号恢复与清理**
  - 恢复 `refresh.go` 额度探测复活机制，失效/待重登账号探测成功自动回池
  - 恢复密码 + TOTP 协议登录恢复链路（`oauth.LoginWithPassword`）
  - 每日验活：优先协议恢复，其次额度探测；只有恢复失败才判真死号
  - 实现 `/api/accounts/cleanup/preview` 与 `/api/accounts/cleanup/run`
  - 「自动移除异常账号」开启后，仅删除确认真死号；正常、待重登、生图失效账号不删
  - 账号页「每日验活」「协议恢复」开关接入 `/api/scheduler`
- **面板与发布**
  - 账号页新增「待重登」「生图失效」状态与筛选
  - 前端嵌入不再写死 hash 文件名，重新构建不会导致 Go embed 失败
  - 版本号统一为 `24.2`

## 24.1

**类型**：源码对齐 + 部署修正（无新功能）

- **源码对齐服务器生产树**
  - 297 个 `internal/cmd/go.mod/go.sum` 文件与服务器 `/root/chat2api` 字节级一致（生产 23.0-fix10 实际运行源码）
  - 删除本地分叉、服务器不存在的模块：`internal/superres/`、`internal/scheduler/{settings,token_exp}.go`、`internal/settings/settings.go`、`internal/account/oauth/{sentinel,totp}.go`、`internal/api/admin/{gallery,logs,monitor,scheduler}.go`、`internal/api/{settings,provider_conn}.go`
  - 清理误提交的临时脚本与源码快照：`_s*.py`、`server_src/`、`src_snapshot/`
- **RegiForge 导出器重写**（`regiforge/export/chatgpt2api/provider.py`）
  - 改为单账号 `POST /api/accounts` + `quota_unknown`，修掉此前批量导入的失败
- **前端产物同步**：`internal/api/web_dist/assets/*` 更新为服务器当前版本
- **Dockerfile**：入库「服务器叠加构建」版（golang:1.26-alpine 编译 + 23.0 运行层）
- **修正标签与内容不一致**：`VERSION` 与 CI `TAG_MAJOR` 由错误的 Python 项目版本 `v3.2.1` / `24.0` 统一为 `24.1`

> 说明：git tag `24.0` 是个残次品——该次提交未包含 fix1~fix10，CI 据此构建的 24.0 镜像缺失修复。
> 线上实际运行的 `zhoushu1/chat2api:24.0` 镜像内是 fix1~fix10 之后的代码，即本 tag 24.1 对应的源码。

## 24.0

- RegiForge 导出器重写（bug 修复）

## 23.0

- **核心修复**：批量套图结果大量重复 —— `GenerateImage` 轮询时排除参考图 `FileID`

## 22.0

- 修 Bug：日志详情误报错误

## 21.0

- 修复验活误杀（39 僵尸号根因）

## 20.1

- 修复协议恢复与额度：真 `sdk.js` 求解 sentinel；额度改用 `conversation/init`
- CI 镜像标签 20.0 -> 20.1

## 20.0

- CI 镜像版本标签 19.0 -> 20.0

## 19.0

- 真实 2K/4K：尺寸校验放开 + 精确缩放 + 4 倍档转 JPEG
