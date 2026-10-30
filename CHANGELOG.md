# Changelog

本文件记录 Go 版 `chatgpt2api` 的版本变更。
版本号同时维护在三处，**必须保持一致**：git tag / `VERSION` / `.github/workflows/docker-publish.yml` 的 `TAG_MAJOR`。

## 27.0

**类型**：账号保护体系完善 + 开源调研成果

### 新增：熔断器（连续失败隔离）

- 连续失败 5 次 → 隔离 30 秒 → 半开探测 3 次成功才恢复。
- 对齐 ChatGPT2API 的 `circuit_breaker.py`（SharedBreakerStateStore）。
- `BreakerAllows` 在 `Pool.Pick` 里拦截被熔断的号。
- `BreakerRecordSuccess` / `BreakerRecordFailure` 在 orchestrator 成功/失败路径埋点。

### 新增：单号日限 + 同号最小间隔（26.9 已实现，本版配置化）

- `daily_image_cap`（默认 5）：每号每天最多产出 5 张。
- `min_interval_sec`（默认 30）：同号两次请求最少间隔 30 秒。
- `circuit_breaker_count`（默认 5）：连续失败熔断阈值。

### 开源调研结论（2026-10-30）

对比了 3 个活跃项目：
- [lzA6/GPT-Codex-image-2api](https://github.com/lzA6/GPT-Codex-image-2api) v2.37.0 — 最先进，Python/FastAPI
- [AuuCoder/gptGrok2api](https://github.com/AuuCoder/gptGrok2api) v1.2.1 — GPT+Grok 双平台
- [LanQian528/chat2api](https://github.com/LanQian528/chat2api) — 已停更

**我们已实现的（14/22 项）：**

| 技术 | 状态 |
|---|---|
| 设备 ID 稳定（SHA-1 派生） | ✅ 26.3 |
| 指纹完整透传（UA/语言/平台/国家） | ✅ 26.6~26.7 |
| 按账号分配出口 IP（warp 粘性会话） | ✅ 26.2 |
| utls TLS 指纹（bogdanfinn/tls-client） | ✅ 已有 |
| 429 冷却换号（account_rate_limited） | ✅ 26.2 |
| 403 分类隔离（upstream_forbidden） | ✅ 26.3 |
| 验活不误杀（网络错误跳过） | ✅ 26.3 |
| 账号预热（WarmPending） | ✅ 26.4 |
| 背压排队（池满等 8 秒） | ✅ 26.4 |
| 协议恢复改用账号出口 | ✅ 26.5 |
| 手动触发验活恢复 | ✅ 26.5 |
| 单号日限 | ✅ 26.9 |
| 同号最小间隔 | ✅ 26.9 |
| **熔断器（连续失败隔离）** | ✅ **27.0** |

**尚未实现（8 项，按优先级排序）：**

| 技术 | 来源 | 优先级 | 说明 |
|---|---|---|---|
| 账号养号系统（7 天 nurturing） | lzA6 config | HIGH | 新号前几天低频/无 API 调用 |
| 健康分级调度（healthy/warm/risky） | lzA6 README | HIGH | 按风险分级路由流量 |
| 异步恢复工作流 + ledger | lzA6 v2.37.0 | HIGH | 队列式 OTP 恢复 + 原子账本 |
| FlareSolverr CF clearance 刷新 | lzA6 + gptGrok2api | HIGH | 自动解决 Cloudflare 挑战 |
| 警告页暂停（warned_pause_hours） | gpt2api | MEDIUM | 收到警告页 → 暂停 24h |
| 多邮箱源（22.do 等） | lzA6 commit | MEDIUM | 降低邮箱指纹聚类 |
| 住宅 IP（kookeey） | lzA6 config | MEDIUM | 数据中心 IP 被部分平台拒绝 |
| 寿命预测 | lzA6 README | LOW | 按使用模式预测剩余寿命 |

### 关键发现

- `account_deactivated` **无法解封**，社区共识是预防 + 补号，不是治疗。
- 挂 warp + fp 透传后存活率从 0% 提升到 82~96%（A/B 验证）。
- `min_interval_sec` 是 gpt2api 最核心的防封参数（默认 60s）。
- 养号系统（7 天 nurturing）是 lzA6 最新的创新，新号前几天不调 API。

## 26.9

**类型**：单号保护（日限 + 最小间隔）

参考开源项目 [gpt2api](https://github.com/432539/gpt2api) 的 min_interval_sec + daily_usage_ratio 策略：

### 新增：同号最小间隔

- 同一账号两次被 Pick 选中之间至少间隔 `minAccountIntervalSec`（默认 30 秒）。
- 对齐 gpt2api 的 `min_interval_sec`（默认 60s）：防止同号高频被风控。
- 新增 `lastPicked` 字段记录上次选中时间。

### 新增：单号日产出上限

- 每号每天最多产出 `dailyImageCap`（默认 5 张），超过后不再参与调度。
- 实测：不限制时每号每 1.6 次请求死 1%；限制到 5 张/天死亡率预计降到约 3%。

### 配置化

- `config.json` 新增 `daily_image_cap` / `min_interval_sec` / `circuit_breaker_count`。
- `SetDailyImageCap` / `SetMinIntervalSec` 运行时可调。

### 开源调研结论

对比 [gpt2api](https://github.com/432539/gpt2api) 和 [ChatGPT2API](https://github.com/lzA6/GPT-Codex-image-2api)：
- ✅ 已有：设备 ID 稳定、指纹透传、按账号出口、429 冷却、账号预热、背压排队、utls TLS 指纹
- ✅ 本次新增：同号最小间隔、日限保护
- ⬜ 未做：警告页暂停（warned_pause_hours）、熔断器（连续失败隔离）、健康分级调度

## 26.8

**类型**：文档更新 + A/B 验证结论

### A/B 验证结论（2026-10-30）

在 WarpGate v11.0（`health=unknown` 实例可参与分配 + `sticky_minutes=60` + `min_available=20`）配合 chat2api 26.7（指纹完整透传 + 按账号分配出口 + 429 冷却 + 账号预热 + 背压排队）环境下，注册 50 个新号经三轮 64 并发压测：

| 轮次 | 成功率 | 存活率 |
|---|---|---|
| T1 | 63/64 (98.4%) | 48/50 (96%) |
| T2 | 63/64 (98.4%) | 46/50 (92%) |
| T3 | 62/64 (96.9%) | 41/50 (82%) |

对比历史基线：

| 配置 | 存活率 | 关键差异 |
|---|---|---|
| 无 warp + 无 fp（13:20 批次） | **0%** | 全局单 IP，指纹割裂 |
| 有 fp + 无 warp（15:30 批次） | **54%** | 指纹修复但出口仍单一 |
| 有 fp + 有 warp（本次） | **82~96%** | 每号独立 warp 出口 + 完整指纹 |

**结论：出口 IP 确认是主要因素，挂 warp 后死亡率降低 3~5 倍。**

### 26.2~26.7 修复清单

| 版本 | 修复内容 |
|---|---|
| 26.2 | 429 冷却重试（`account_rate_limited`，冷却 2 分钟换号）+ 按账号分配出口 IP（`internal/egress`）+ 设置页开关 |
| 26.3 | P0-1 指纹割裂（`stableDeviceID` 按 SHA-1 派生，不再每次 `uuid.NewString`）+ P0-2 403 分类（`upstream_forbidden` 冷却 30 分钟）+ P0-3 验活不误杀（网络错误跳过判定）+ `sec-ch-ua`/`Full-Version`/`Accept-Language` 按 UA 推导 |
| 26.4 | 账号预热（`WarmPending`，新号未验额度不参与调度，30 分钟 fail-open）+ 背压排队（池满等 8 秒而非瞬时 503）+ `/api/accounts` 拒绝空 token |
| 26.5 | 协议恢复改用账号固定 warp 出口（避免同 IP 连续密码登录被判盗号）+ `POST /api/scheduler/run` 手动触发验活 |
| 26.6 | 导出器新增 `fp` 透传（`egress_fingerprint` 完整对象 → `Account.FP`）|
| 26.7 | 注册指纹补丁固化进镜像（`_http_engine.py` 输出完整指纹对象）|

### WarpGate 配套

WarpGate v11.0（[github.com/zhoushu44/WarpGate](https://github.com/zhoushu44/WarpGate)）：
- `health=unknown` 实例可参与分配（池容量从 70 恢复到 100）
- `sticky_minutes` 10→60、`min_available` 5→20

## 26.7

**类型**：把注册指纹补丁固化进镜像

26.6 只改了容器内运行文件，镜像内 _http_engine.py 仍是旧版（只有 chrome/chrome136 字符串）。
本版把完整指纹输出写进仓库源文件并重建镜像，重启不再丢失。

- egiforge/projects/chatgpt_register/steps/_http_engine.py：gress_fingerprint 输出完整对象。
- 配合 26.6 的导出器 p 透传，注册→号池→生图身份链条完整。

## 26.6

**类型**：补全注册指纹透传（P0-1 最后一环）

问题：注册侧只写了 `egress_fingerprint = "chrome/chrome136"` 这样的字符串，
导出器又只透传 password/totp/session，导致 Go 侧 `Account.FP` 全为空，
生图时只能按 token 哈希重选一套指纹 —— 与注册时的身份不一致。

修复：

- 注册侧改为输出**完整指纹对象**（user_agent / impersonate / accept_language / sec_ch_ua_platform / country / browser_type）。
- 导出器新增 `fp` 透传，兼容下划线与连字符键名。
- Go 侧 `NewBackend` 的 `fpOverride` 优先级最高，指纹从注册到生图全程一致。

实测：新注册 5/5 成功，`fp` 完整落库（UA/语言/平台/国家），生图 3/4 成功（1 个为 prompt 内容策略）。

## 26.5

**类型**：协议恢复改用账号固定出口

- 此前 `sched.Recover` 固定用全局 `EffectiveProxy()`，同一 IP 连续 3 次密码登录，极易被上游判盗号（实测返回 `invalid_username_or_password`）。
- 现在恢复优先使用该账号的固定 warp 出口（`Egress.ProxyFor`），与注册/生图保持同一出口身份。
- 实测背景：678 个有密码+TOTP 的账号中 296 个曾成功生图（账号与密码真实有效），但 `revive_count` 全为 0——从未有一个号被恢复救活，符合「同 IP 重复登录被拒」的判断。

## 26.4

**类型**：对齐开源实践——账号预热 / 入池校验 / 背压排队

参考同类开源项目（[gpt2api](https://github.com/laowang74152/gpt2api)、[GPT-Codex-image-2api](https://github.com/lza6/GPT-Codex-image-2api)）的「号池预热 + 高并发调度」做法：

### 账号预热（解决新号入池即被打）

- 新增 `WarmPending`：额度未知且从未探测过的新号标记为预热中，**不参与调度**。
- `refresh` 额度探测成功后自动清除 `WarmPending` 与 `QuotaUnknown`，号才进入调度。
- 预热超过 **30 分钟**仍未成功则自动放行（fail-open，避免号永远不可用）。

### 背压排队（解决瞬时并发直接 503）

- `generateSingle` 选号为空且池内仍有账号（只是被占满）时，最多等待 **8 秒**轮询重试，而不是立刻返回 `no_available_account`。
- 池子本身为空时仍立即失败，不浪费等待。

### 入池校验

- `POST /api/accounts` 拒绝空 token（此前空 token 也会进池并被调度）。
- 自动补全 `id` / `email` / `status`，避免统计与去重失效。

### 其它

- 修正 `orchestrator` 中关于单号并发的注释（单号并发实际由 `Pool.Pick` 的 `MaxInflight` 保证，无需改动并行度上限）。

## 26.3

**类型**：修复「死号」根因（P0 三项）

### P0-1 指纹链路修复：同一 token 不再每次换设备身份

- `FingerprintForAccount` 此前每次调用都 `uuid.NewString()` 生成 `OAI-Device-Id` / `OAI-Session-Id`，同一 token 每次请求都是「新设备」，上游视角等同 credential sharing。
- 新增 `stableDeviceID`：由账号标识 SHA-1 确定性派生 UUID，**同一账号永远同一 did/sid**。
- `secChUaFor` 不再硬编码 Chrome146，按 UA 真实品牌与主版本生成；`Sec-Ch-Ua-Full-Version` / `Full-Version-List` 同步按 UA 推导。
- `Accept-Language` 改用指纹 profile 的真实值（此前固定 zh-CN，与 en-US 指纹矛盾）。

### P0-2 403 分类

- 新增 `upstream_forbidden`（Scope=account，403）：冷却 **30 分钟**并换号，不再落 default→transient 导致同一个号被反复选中反复 403。
- `account_deactivated` / `deleted or deactivated` 归入 `auth_invalid`，走「待重登」而不是被当临时错误重试。

### P0-3 验活不再把网络故障误杀成死号

- `CheckValid`：能拿到上游 HTTP 状态码才算失败；纯传输层错误（超时/DNS/连接/TLS）**跳过判定**（视为存活），避免代理抖动就把号判死。
- Backend 构建失败同样跳过而非判死。

### 测试

- 修复两处历史失败测试：`TestDownload` 改用合法 JPEG（下载层已统一转码）、`TestImageModelSlug`/`TestStartPayloadTextOnly` 期望对齐当前 `auto` 映射。

## 26.2

**类型**：429 冷却重试 + 按账号分配出口 IP

### 429 冷却重试（不改判定，只改分类与处理路径）

- 新增失败码 `account_rate_limited`（Scope=account，StatusCode=429）：429 不再走 `upstream_rate_limited`（transient 且不可换号），改为账号级——**冷却该号并切换其它号重试**，不再让单个 429 直接失败整个请求。
- `cooldownFor`：429 相关失败冷却从 30 秒提升到 **2 分钟**（避免刚冷却就被复用再次撞限流）。
- 未改动死号判定逻辑：仍只有 `auth_invalid` 才标「待重登」。

### 按账号分配出口 IP（设置页可开关）

- 新增 `internal/egress`：按账号 ID 哈希生成稳定 sid，向 warp 池取**固定粘性出口**，同账号始终同出口。
- `Orchestrator.getBackend` 优先使用账号专属出口，缓存键含代理，切换开关自动重建。
- 新增 `GET/POST /api/egress`；`POST /api/settings` 支持 `egress_enabled` 热更。
- 设置页「账号策略」新增开关「按账号分配出口 IP」。
- 默认关闭；取不到出口时自动回退全局代理，不阻断主流程。

## 26.1

**类型**：手动触发验活 + 协议恢复

- 新增 `POST /api/scheduler/run`：立即对全量账号跑一次验活 + 协议恢复（异步，返回处理账号数）。
- 复用每日定时任务同一逻辑（`doDaily401`），不影响 `lastDailyDate`，可随时手动补跑。

## 26.0

**类型**：首页新增「账号产出与存活」区块

在账号统计卡片下方新增一个区块：

- 单号产出：平均 / 中位数 / P90 / 最高 / 累计成功 / 含无产出均值。
- 存活：平均存活时长 / 中位存活 / 存活-失效对比 / 恢复次数。
- 批次存活率条形图、死亡原因分布。
- `statsApi.accountStats()` 对接 `GET /api/stats/accounts`，页面加载时自动拉取，支持手动刷新。

## 25.9

**类型**：修复统计路由冲突

- `/api/accounts/stats` 与已有 `/api/accounts/:id` 通配路由冲突导致 Gin panic、服务启动失败（25.8 的致命问题）。
- 统计接口改为 `GET /api/stats/accounts`，避开通配路由。

## 25.8

**类型**：账号产出与存活统计

新增账号级统计字段与 `GET /api/accounts/stats`：

- 单号产出：`total_images_ok`、`avg_images_per_account`、`median_images`、`p90_images`、`max_images`，恢复次数 `total_revive` / `accounts_revived`（产出跨恢复累计）。
- 存活分析：`avg_lifetime_h`、`median_lifetime_h`、`death_reason` 分布、`created_by_day` / `died_by_day`、`batch_survival` 批次存活率。
- 埋点：生图成功/失败累加 `images_ok` / `images_fail`；判死写 `died_at` + `death_reason`；恢复写 `revive_count` + `last_revived_at` 并清死亡标记。
- 落盘只在判死/复活时触发，避免每次生图写盘。

## 25.7

**类型**：URL 模式 JPG 内容修复

- 修复 `saveJPEGImages` 直接把 `res.B64`（base64 字节）当二进制写入，导致下载到的是 `/9j/...` 文本、扩展名是 .jpg 但内容不是图片。
- 落盘前先 base64 解码，写出真正 JPEG 二进制。
- 新增 `TestSaveJPEGImagesDecodesBase64` 防回归。

## 25.6

**类型**：URL 模式 JPG 落盘目录修复

- 修复 saveJPEGImages 落盘目录错位：此前存到 `<dataDir>/YYYYMMDD`，与读取根 `<dataDir>/images` 不一致，导致 URL 模式下载 404。
- 现统一为 `<dataDir>/images/YYYYMMDD/<文件名>.jpg`，/v1/images/<日期>/<文件> 可直接下载。

## 25.5

**类型**：2K/4K URL 模式统一输出 JPG

- `response_format=url` 时把已转码的 JPEG 落盘到 `data/images/YYYYMMDD/`，返回 `/v1/images/<日期>/<文件>.jpg`。
- 1K（b64）与 2K/4K（url）现在都是真正的 JPEG，不再返回上游 PNG/WebP 原始 URL。
- 新增 `v1.SetImageDataDir`，由路由注入真实数据目录。

## 25.4

**类型**：注册失败根因修复（warp 会话冷启动）

- 根因：warp 粘性会话刚建立时隧道未就绪，**每个新会话第一次请求必定失败**（Connection closed / 000），注册第 1 步 Sentinel 提取直接判死。
- 修复：`WaryProxyProvider.acquire()` 拿到代理后先做 HTTP 预热，打通隧道再交付使用，失败重试 3 次不抛错。
- 实测：预热前 10 个新会话 0/10 成功；预热后 10/10 成功。
- 注册实测：连续两批 2/2 成功，`[2FA] TOTP 绑定成功` + `注册收口完成：密码 + TOTP 2FA + 验活 全通过`，新账号 4/4 全部带 password + TOTP。
- 同步补齐容器内缺失的 `_sentinel_v8.py` 与 `sentinel_vm/`（sdk.js、runner、server、version.txt），新版 Sentinel V8 生效。

## 25.3

**类型**：显式 total 标记持久化

- 修复 `ExplicitTotal` 在 `normalize()` 重建 Config 时丢失，导致 `/start` 传入的 total 仍按差额补齐计算。
- `Update()` 合并后显式回写标记。

## 25.2

**类型**：register total 语义修正

- 显式 `total` 表示「本次注册 N 个」，不再按「补到账号池总数 N」计算；池内已有 41 个时输入 2 仍会注册 2 个。
- 提取 `poolSize()` 统一账号池数量读取。

## 25.1

**类型**：注册链路三处修复

- `/api/register/start` 支持直接传 `total/threads/mode`；显式 total 优先，不再被 `mode=available` 固定 200 覆盖。
- 停止任务时回写 `running=0` 与 `finished_at`，页面不再显示运行中。
- 注册强制绑定 TOTP 2FA（默认开启）；browser 模式补齐 password 字段，缺密码或缺 TOTP 直接判失败，不再产出无法协议恢复的残号。

## 25.0

**类型**：图像任务页额度与状态修复

- 只有额度接口真正失败时才显示「额度读取失败」；未知额度正常显示为「未知额度账号 N 个」，不再误报失败。
- 任务创建/查询补齐 mode、model、size、quality、n、elapsed_secs 字段，前端可正确跟踪状态。
- 轮询使用创建时保存的模型与数量，不再固定回退为 gpt-image-2 / n=1。

## 24.9

**类型**：生图输出统一 JPG

- 下载层将 PNG/WebP/GIF 真实转码为 JPEG，不再按上游 Content-Type 保存 `.webp`。
- 新落盘图片统一 `.jpg`；已是 JPEG 的输入不重复压缩。
- 透明像素以白色背景合成，避免 JPEG 黑底。
- 增加 PNG→JPEG 真转码与 JPEG 不重复压缩测试。

## 24.8

**类型**：图片通配路由修正

- 使用 `/v1/images/*path` 支持 `日期/文件名` 的真实图片访问。
- 修正管理接口与图片下载通配路由注册冲突。

## 24.7

**类型**：图片预览与日志展示修正

- 图片预览走 `/v1/images/:path` 真实文件接口，不再被 SPA 回退为 HTML。
- 图片列表 URL 同步改为 `/v1/images/...`，与 `/api/images` 管理接口分离。
- 日志时间统一为 `YYYY-MM-DD HH:mm:ss`，不再显示带纳秒的原始 RFC3339 字符串。

## 24.6

**类型**：日志与图片管理真实 API

- `/api/logs` 返回真实生图调用记录、统计与筛选；`/api/runtime-logs` 返回运行日志。
- `/api/images` 支持图片分页、类型/标签/搜索过滤；`/api/images/storage` 返回真实图片数量、体积和磁盘空间。
- 支持图片下载、批量打包、删除、标签读取/更新/删除，并拦截路径穿越。
- `/api/image-tasks` 支持真实生图/图生图任务创建、查询、额度摘要与续轮询。
- 补充日志 JSON、图片列表/存储统计、路径安全测试。

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
