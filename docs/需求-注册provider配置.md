# 邮箱配置 + 代理配置（迈巢邮箱框 + warp 代理框，可扩展）

> 单独需求文档。把注册用的邮箱和代理做成面板两个独立配置框，可输入 url/key 等配置，带测试 + 保存按钮。
> 框内当前显示：邮箱=**迈巢**（mailnest）、代理=**warp**（自托管 warp-pool）。
> **可扩展**：邮箱框/代理框是通用配置区，当前 provider 是迈巢/warp，后续可加其他邮箱和代理 provider，每个 provider 自带字段，面板自动可选。
> 原版 :3000 不动；真实测试通过才算过。

---

## 一、两个配置框（核心，可扩展）

面板「注册」配置页显示**两个独立配置框**，每个是「provider 类型可切换 + 字段输入 + 测试 + 保存」的通用配置区：

### 框 A：邮箱配置框（当前显示「迈巢邮箱框」）

- **显示**：面板注册配置页一个「邮箱配置」区，顶部可切换邮箱 provider 类型（当前=迈巢 mailnest，后续可加其他）
- **输入字段**（随 provider 变，迈巢的字段）：
  - `url`：mailnest API base url
  - `api_key`：mailnest API key
- **测试按钮**：用 url+api_key 调 mailnest API → 返回 成功/失败 + 可用邮箱数
- **保存按钮**：持久化当前选中的 provider + 配置，重启保留

### 框 B：代理配置框（当前显示「warp 代理框」）

- **显示**：面板注册配置页一个「代理配置」区，顶部可切换代理 provider 类型（当前=warp，后续可加其他如 mihomo）
- **输入字段**（随 provider 变，warp 的字段）：
  - `url`：代理地址（如 `socks5://warp-proxy:1080` 或 `http://192.6.121.16:8118`）
  - `key`：可选认证（warp-pool 如需认证才填）
- **测试按钮**：用该 url 测连通 → 返回 成功/失败 + 出口 IP + 延迟
- **保存按钮**：持久化当前选中的 provider + 配置，重启保留

### 可扩展设计（关键）

- 邮箱框/代理框是**通用配置区**：顶部选 provider 类型，下方按该 provider 的字段定义**动态渲染**输入框
- 当前邮箱 provider=迈巢（mailnest），代理 provider=warp
- **后续加新邮箱/代理**：只需在 `registry.go` 新增 provider 定义（含字段 schema），面板自动可选 + 渲染对应字段，无需改前端逻辑
- 注册任务用「当前选中的邮箱 + 代理」配置，不再回退 RegiForge 抽象 id `mailnest`/`wary`

---

## 二、现状调研（2026-09-09）

- **Go provider 体系**（`internal/provider/registry.go`）：已有 `mihomo`/`api_extract`/`static_pool`（代理）、`local_ms_pool`/`api_mailbox` 等（邮箱），**无 warp/mailnest 定义**；`Setting.Config/Auth/Meta` 是 `map[string]any`（无固定 url/key 字段）。
- **`register.json`**：`mail.providers=[{id:"regiforge-mailnest",type:"gptmail",api_key:"",...}]`（占位空 key）；顶层 `proxy:""`；`channel={email_id:"mailnest",proxy_id:"wary",...}`。
- **面板 API**（`internal/api/providers.go`）：`GET/PUT /api/provider_settings/:type/:key`，**无测试接口**；`/api/proxy_nodes` 是生图代理池，非注册。
- **前端**（`web_dist/`）：注册页**无代理/邮箱配置框**。
- **语义**：warp = 自托管 `zhoushu1/warp-pool` 容器（socks5/http url）；迈巢 = RegiForge 侧 mailnest 邮箱 provider，真实 url/key 在 RegiForge 内，Go 现不持有。

---

## 三、现状对照

| 项 | 现状 | 目标 |
|---|---|---|
| 邮箱配置 | RegiForge id `mailnest`（Go 不持 url/key） | **框 A 邮箱配置框**：迈巢邮箱框（url+api_key），可扩展其他邮箱 |
| 代理配置 | RegiForge id `wary`（Go 不持 url） | **框 B 代理配置框**：warp 代理框（url+可选 key），可扩展其他代理 |
| 面板 | 无配置框 | 两框 + provider 可切换 + 测试 + 保存 |
| 测试 | 无 | 邮箱测 key、代理测连通 |
| 持久化 | env/抽象 id | register.json provider config（含选中类型+字段），重启保留 |
| 扩展 | 无 | 新增 provider 定义 → 面板自动可选 + 渲染字段 |

---

## 四、涉及代码

| 文件 | 改动 |
|---|---|
| `internal/provider/registry.go` | 新增 `warp` 代理 + `mailnest` 邮箱 provider 定义（含字段 schema：url/key/api_key）；架构支持后续加新 provider |
| `internal/api/providers.go` | 扩展 `GET/PUT /api/provider_settings`（含 provider 类型 + 字段），新增测试接口 `POST /api/provider_settings/:type/:key/test` |
| `internal/register/` | 注册任务用当前选中的邮箱 + 代理 provider 配置（映射 bridge 或直接用） |
| `web_dist/` | 框 A 邮箱配置框（迈巢）+ 框 B 代理配置框（warp），顶部 provider 可切换，字段按定义动态渲染 |

---

## 五、验收门禁（缺一不过）

- [ ] 面板注册配置页显示 **框 A 邮箱框（迈巢）** + **框 B 代理框（warp）**
- [ ] 每框输入 url/key，点**测试**返回验证结果（迈巢可用邮箱数、warp 出口 IP）
- [ ] 点**保存**持久化（provider 类型 + 字段），重启后配置仍在
- [ ] 注册任务用保存的邮箱 + 代理配置（日志可见），不再回退 RegiForge 抽象 id
- [ ] **扩展性**：新增一个 provider 定义（mock）→ 面板下拉自动出现 + 渲染其字段，无需改前端
- [ ] 原 :3000 不受影响（未改 Python 容器/配置/数据）

---

## 六、与主需求表对应

主表模块 **M9 邮箱配置 + 代理配置（迈巢邮箱框 + warp 代理框，可扩展）**，状态 🔴 待做（顺序用户定）。
