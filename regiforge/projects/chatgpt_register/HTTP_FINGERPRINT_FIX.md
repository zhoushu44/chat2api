# ChatGPT HTTP 注册死号修复（方案 A → A+：指纹对齐 + 随机化 + 地理联动）

> 状态：方案 A 已实测——**注册全部通过，但账号"慢慢死"**：每个账号生成 1-3 张图后失效，约 20 分钟内全灭。
> **A+（指纹随机化 + 地理联动 + 全套 CH）尚未开始测试**，见 §8 实测记录。
> 文档顺序：背景 → 根因 → A（对齐）→ A+（随机化/联动）→ 已知边界 → 验收 → 备选 B → 实测记录。

## 1. 背景与现象

- 项目：`chatgpt_register`，`register_mode=http`（Sentinel + curl_cffi 协议注册）
- 现象演进：
  - 修复前：注册流程能跑通、拿到 access_token，但账号"一下死"（秒级被识别）
  - 方案 A（TLS/头/时序对齐）后：注册全部通过，但账号**使用中慢慢死**（20 分钟全灭，每账号 1-3 张生图）
  - 方案 A+（随机化 + 地理联动 + 全套 CH）：已部署，**待实测**

## 2. 链路与根因

链路：`浏览器(Patchright) 提取 Sentinel token → curl_cffi 发注册 API 请求`

| # | 根因 | 修复归属 |
|---|------|---------|
| 1 | TLS 指纹与 UA 版本不一致（`impersonate="chrome"` 模糊） | A |
| 2 | 缺 Client Hints（sec-ch-ua*）与 sec-fetch-* 头 | A |
| 3 | 缺人类时序（取完 token 立即打 API） | A |
| 4 | **批量同指纹**：全账号固定 Chrome/131/Windows/en-US 一套 → OpenAI 反欺诈最大关联信号（开源项目实测批量存活率 ~2%） | **A+** |
| 5 | **IP 地理不联动**：代理 IP 在日本/泰国，指纹仍是 en-US + America/New_York → 语言/时区与 IP 国家不符 | **A+** |
| 6 | Sentinel token 上下文断裂（浏览器生成 token、curl 发请求） | 边界，根治靠 B |

参考：开源项目 [Regert888/gpt-outlook-register](https://github.com/Regert888/gpt-outlook-register)（纯协议批量注册）明确做了**指纹随机化 + IP 地理联动**（`fingerprint.py`），并用 curl_cffi 精确 impersonate。

## 3. 方案 A（已实施）：指纹对齐

保持「浏览器提 token + curl 发请求」架构，保证**单账号**指纹自洽：

- 版本动态对齐：`_sentinel.impersonate_for_ua` / `sec_ch_ua_for` 按 UA 版本映射 TLS 指纹与 Client Hints
- `_http_engine._browser_headers`：统一构造 `sec-ch-ua*` / `Accept-Language` / `sec-fetch-*`
- sec-fetch 语义：同源 API `cors/empty`；signin 表单 / OAuth 跳转 / 会话导航 `navigate/document` + `upgrade-insecure-requests`
- 人类时序：Sentinel 提取后随机延迟 1~3s

**局限**：单一固定指纹 + 无地理联动 → 批量注册时所有账号同画像，仍被识别。

## 4. 方案 A+（已实施）：指纹随机化 + IP 地理联动

### 4.1 指纹生成模块（新文件 `_fingerprint.py`）

- **多浏览器家族带权重**：chrome 55% / firefox 25% / safari 20%；每次注册随机一套
- 家族版本表（curl_cffi 0.15.0 实测可构造）：
  - chrome：`chrome131/136/142/145`（UA、sec-ch-ua、GREASE 变体同步；**全套 Client Hints**：`sec-ch-ua-full-version-list`（真实完整版 131.0.6778.86 等）/ `arch` `x86` / `bitness` `64` / `model` `""` / `platform-version` `15.0.0` / `wow64` `?0`，主版本与 full 版本严格一致——跟随开源 gpt-outlook-register v0.4.8）
  - firefox：`firefox133/136`（真实不发 sec-ch-ua*，全套字段为空）
  - safari：`safari15_3/17_0/18_0`（同上）
- **一套内全部绑定一致**：impersonate ↔ UA ↔ sec-ch-ua（仅 chrome 家族，firefox/safari 真实不发）↔ Accept-Language ↔ locale ↔ timezone ↔ viewport ↔ 屏幕 ↔ 硬件画像（`navigator.platform/vendor/hardwareConcurrency/deviceMemory/maxTouchPoints/devicePixelRatio`）
- **IP 地理联动画像**：30+ 国家 → 时区（带权重）+ 语言列表；语言首项作为 locale 与 Accept-Language 主语言
- `detect_country(proxy_url)`：经注册同款代理出口查 ip-api.com（免费、无 key）拿国家，失败回退 US

### 4.2 生成策略（`_http_engine.register_http`）

- 每次注册（含整段重试 = 新会话）重新生成一套指纹，日志打 `指纹=family/impersonate locale=.. tz=..`
- **用户显式配置 UA** → 不随机 UA，其余（语言/时区/屏幕/硬件）仍按地理联动随机（`fingerprint_from_user_ua`）

### 4.3 curl 侧接入（`_http_engine.py`）

- `_browser_headers(fp, accept)`：UA / Accept-Language / sec-ch-ua* 全部来自 fp（firefox/safari 不发 Client Hints）
- `_req_kwargs(proxy_url, *, fp=None)`：`impersonate` 取 fp 精确版本（原按 UA 解析的逻辑降级为兜底）
- 全链路请求（CSRF / signin / OAuth / OTP / create_account / session / oauth token）统一透传 fp

### 4.4 浏览器侧接入（`_sentinel.py`）

- `extract_sentinel(..., fingerprint=fp)`：context 的 `user_agent / locale / timezone_id / viewport` 用 fp（与 curl 完全一致）
- `add_init_script` 注入 navigator 硬件画像（platform / vendor / hardwareConcurrency / deviceMemory / maxTouchPoints / devicePixelRatio）
- 拉 sdk.js 的 `_fetch_text` / `_inject_sdk_via_eval` 用 fp 的 impersonate

### 4.5 一致性保证

同一次注册内，**curl 请求头画像 == 浏览器 context 画像 == 代理出口国家画像**。三者任一不一致即风控信号。

## 5. 已知边界（有意不做的项）

| 项 | 原因 |
|----|------|
| 全套 Client Hints 已实现但属"尽力对齐" | 真实浏览器仅在收到 `Accept-CH` 响应后回发 `sec-ch-ua-full-version-list/arch/...`；我们直接全发（跟随开源 v0.4.8），若 OpenAi 不请求则这些头多余但无害 |
| cookie Secure/HttpOnly 标志 | `_apply_sentinel_cookies` 手动 set 无 Secure；CSRF 走 JSON `csrfToken` 不走 cookie |
| **token 上下文断裂** | 浏览器生成 token + curl 发请求的结构性差异，**A/A+ 只能尽力对齐**；仍死号则切方案 B |
| Canvas/WebGL/WebRTC 深层指纹 | curl 侧不存在这些 API；浏览器侧由 Patchright + 系统 Chrome 兜底 |

## 6. 验收标准

1. 单账号 `concurrency=1` HTTP 注册跑通，`status=ok` 有 access_token
2. 日志确认：每次注册指纹不同（家族/版本随机），locale/tz 与出口国家匹配
3. 账号**次日存活**为硬标准；本次目标是对比 A 的"10 分钟死号"有本质改善
4. 连续 `total≥5` 样本，成功率较修复前有提升（进入 L2 复验）
5. 若仍批量死号 → 判为 token 上下文断裂，切方案 B

## 7. 备选方案 B（若 A+ 无效再启用）

- QuickJS 跑 OpenAI 真 `sdk.js` 生成 Sentinel token（仿 gpt-outlook-register `sentinel_quickjs.py`），去掉浏览器，token 生成与请求全程 curl 指纹一致
- 依赖：node.js ≥ 18；改动：新增 `_sentinel_quickjs.py` + `_http_engine` 调用切换
- 注意：B 仍需要 A+ 的指纹随机化（QuickJS 版同样要每账号一套指纹），两者互补

## 8. 实测记录与失败模式变化（重要）

### 8.1 实测对比

| 版本 | 注册 | 账号寿命/生成数 | 失败模式 |
|------|------|-----------------|---------|
| 修复前（固定 chrome/UA，无对齐） | 跑通 | 秒级 | **一下死** |
| **方案 A**（版本对齐/时序） | **全部通过** | **~20 分钟，每账号 1-3 张生图后失效** | **慢慢死** |
| **方案 A+**（随机化+地理联动+全套 CH） | 全部通过（本次 1/2，另 1 个代理断链） | **连续成功 16 张**（约 15 分钟）；第 17 张 `auth_invalid`，重试 → 账号判 invalid → 异常（quota=0） | 高频连续生图约 16 张后 OpenAI 端撤销会话，**不可恢复**；但产量较 A 提升 5 倍+，且过程中无风控标记 |

### 8.2 "慢慢死"意味着什么

- 注册阶段（Sentinel + OTP + create_account）已**完全通过**，token 能驱动 `/backend-api` 正常生图 1-3 张 → 指纹/上下文**注册链路问题已解决**
- 方案 A 是**固定单一指纹**（全批量同 chrome131/Windows/en-US）——A 的"20 分钟死"确实含**同指纹批量关联**因素
- **A+ 实测证实**：随机化 + 地理联动后，单账号连续 16 张无风控标记 → 同指纹关联是之前"1-3 张死"的主因之一

### 8.3 根因假设（按概率排序，A+ 已排除前两项）

| # | 假设 | 特征 | 验证实验 |
|---|------|------|---------|
| ~~1~~ | ~~同指纹批量关联~~ | ~~A 固定单一指纹~~ | **已验证排除**：A+ 单账号 16 张无异常 |
| ~~2~~ | ~~注册上下文断裂~~ | ~~浏览器 token + curl 请求~~ | **已排除**：16 张全成功，token 合法可用 |
| 3 | **新账号高频生图触发会话撤销（不可恢复）** | 约 16-17 张后 `auth_invalid`，重试后账号判 invalid（quota=0） | **已验证**：账号不可恢复；需节奏控制/静置/分摊 |
| 4 | **行为节奏太机械**（16 张连续无间隔） | 连续高频触发滥用检测 | 单账号随机间隔（30-90s）+ 达 8-10 张后暂停一段时间 |
| 5 | 新账号 + 新 IP + 立即生图 = 高风险组合被风控 | 使用中断连/撤销 | 注册后先静置再低频使用（单账号间隔 ≥ 30s） |

### 8.4 参考 chatgpt2api 号池经验

逆向项目 [zgm2003/chatgpt2api](https://github.com/zgm2003/chatgpt2api)（同为注册→号池→生图链路）的账号维护侧：

- **号池轮询**：`access_token` 驱动 `/backend-api/conversation`，账号额度/类型/恢复时间自动刷新
- **Token 失效自动剔除**：遇 token 失效类错误自动剔除无效账号
- **限流账号定时刷新**：429/限流账号按恢复时间定时重试
- 关键提示：注册所得是 ChatGPT Web token，**不等于 Codex OAuth 账号**，两者额度独立

### 8.5 当前结论

1. **A+ 显著改善账号存活**：单账号连续 **16 张**生图无风控标记（对比 A 的 1-3 张，提升 5 倍+），证明**指纹随机化 + IP 地理联动是"一下/慢慢死"的主因修复**
2. A+ 实测中另发现并修复的问题：**地理联动缺口**（DZ 等未收录国家回退美国时区 → 已补 16 国画像 + ip-api `timezone` 兜底，`detect_country` 返回 `(country, tz)`）
3. **剩余瓶颈 = 高频行为节奏**：单账号连续 16 张后 OpenAI 端撤销会话（`auth_invalid`，不可恢复）。指纹已不是瓶颈，**行为侧**（新号+连发 16 张无间隔）成为新的限制
4. 下一步方向（按优先级）：
   - **节奏控制**：单账号随机间隔（30-90s）+ 每 8-10 张暂停，或按账号静置策略（注册后先静置再使用）
   - **批量分摊**：多账号并发（号池已有该能力），单账号产量 10-16 张 × N 账号
   - 观察"静置 24h 后是否放宽"，区分额度冷却 vs 会话撤销

## 9. 出口观测日志与出口推荐（2026-08-14）

### 9.1 做了什么

把"哪个出口好"变成可统计数据，不再靠记忆：

- **`_http_engine._append_egress`**：每次注册尝试落盘一条 JSONL（`data/keys/chatgpt_register/egress.jsonl`），字段：
  `ts / email / proxy(去认证 host:port) / country / ip_tz / attempt / fingerprint / locale / timezone / result(ok|retry|fail|fail_exhausted) / error / dur_s`
- **失败也记录**：Sentinel 提取失败、OTP 403、`unsupported_country` 等全部带出口信息落盘——失败样本才是出口质量的关键信号
- **成功账号**：`egress_country / egress_tz / egress_fingerprint` 写入 `accounts.jsonl` 的 extra，可与后续生图存活数据交叉分析
- 日志文本同步打出口：`网络: ... 出口国家: {country}  tz: {ip_tz}`（每次注册/重试）

### 9.2 已知出口实测（本次会话样本）

| 出口国家 | 样本 | 结果 | 结论 |
|----------|------|------|------|
| **US** | 5 注册（任务 e1e326bd3fed） | **5/5 成功**，4/5 token 导入后存活（type=free, quota=25） | ✅ 目前唯一可靠出口 |
| **DZ**（阿尔及利亚） | 注册批 | create_account → `403 unsupported_country_region_territory` | ❌ OpenAI 不支持国家，**直接拒绝** |
| 链路抖动（SSL error 35 / curl 28） | 10 注册批（7 失败） | 超时/断连 → 整段重试消耗邮箱 | ⚠️ 与出口国家无关，但与出口质量强相关 |

> 注：egress.jsonl 从本节起开始累积；9.2 为此前人工观测的既有结论。

### 9.3 下次推荐（按优先级）

1. **固定 US 出口**（mihomo 规则把 chatgpt 流量走 US 节点）——目前 5/5 成功的唯一证据出口
2. **避开 OpenAI 不支持国家**：注册批前先 `detect_country` 探测（已自动做并落盘）；出现 `unsupported_country_region_territory` 立即换出口，不要重试消耗邮箱
3. **出口稳定度 > 速度**：SSL(35)/curl(28) 抖动批成功率仅 30%，宁可慢而稳
4. 累积 ≥20 条 egress.jsonl 后按 `country × result` 聚合，用数据定出口，替换人工记忆

### 9.4 怎么分析（下次批量后）

```bash
# 按出口国家统计注册成功率
jq -r '.country + " " + .result' data/keys/chatgpt_register/egress.jsonl | sort | uniq -c
# 成功账号的出口 + 后续存活（与号池 invalid 交叉）
jq -r '.extra.egress_country' data/keys/chatgpt_register/accounts.jsonl | sort | uniq -c
```

## 10. 开源项目差距扫描（2026-08-14）：指纹已不是瓶颈，行为/用量是

### 10.1 扫了哪些（近 30 天活跃）

| 项目 | 时间 | 与我们相关的点 |
|------|------|----------------|
| [Regert888/gpt-outlook-register](https://github.com/Regert888/gpt-outlook-register) v0.5.5 | 2026-08-12（2 天前） | 我们方案 A/A+ 的指纹参考源；最近更新全是**行为侧**：SMS add-phone 自动接码、注册后自动绑 2FA、错误分类+熔断（连续 3 次网络错误自动暂停）、session_token 三路兜底。明示"批量注册**次日存活率约 2%**" |
| [leeguoo/chatgpt-imagegen](https://github.com/leeguooooo/chatgpt-imagegen)（web 后端） | 2026-06 | 网页生图侧实测结论：**持续 >10 张/分钟、一次几十张 fan-out 会撞限流**；撞限流弹窗 **fail-fast 不重试**；出图对话默认**删除/归进项目**（压低足迹）；并发有上限 |
| 社区实测（CSDN 2026-08-12，3 天前） | 2026-08 | GPT-Image-2 并发安全线：**3 并发 + 2s 间隔 = 稳定；5 并发高峰偶 429；10 并发基本必挨打**；429 看 `Retry-After`，超时**不要立刻重试**（重复计费 + 自我限流） |
| 免费账号真实用量 | 多方实测 | **免费号每天稳定 3-5 张**（网易实测），或 25 张/日配额 |
| OpenAI 风控收紧 | 2026-06 | ChatGPT/Codex 批量封号潮（无预警停用）；Codex 注册新增**手机号验证**（gpt-outlook-register 因此集成 SMS 接码） |

### 10.2 差距结论：我们缺的是"行为/用量侧"，不是指纹

对照 A+ 实测（单账号连续 16 张后 auth_invalid、批量 2-9 张/号）与开源结论：

| # | 开源项目已做 / 已知 | 我们现状 | 差距 |
|---|---------------------|----------|------|
| 1 | 免费号真实用量 **3-5 张/天**；新号第一天猛打 = 滥用信号 | A+ 单账号第一天 16 张、`_gen10_test.py` 3s/张连续循环（约 20 张/分打号池） | **第一天的量远超真实用户**，即使用量节奏正常也会触发风控 |
| 2 | **撞限流 fail-fast 不重试**（重试 = 自我限流 + 更多风险信号） | 生图失败后我们 `_gen_retry.py` / 号池会重试；429/503 后重试把正常账号拖下水（dnf4c82 被 503 误标） | 限流/额度类错误应**立刻停该账号**，不重试 |
| 3 | 并发安全线 3+2s；10 并发必挨打 | 批量测试无 per-account 限速 | 需要 per-account 节奏（间隔随机化 + 上限） |
| 4 | 出图对话**删除/归档**，压低会话足迹 | chatgpt2api 直连 `/backend-api`，不管理会话 | 长期硬刷会积累会话足迹 |
| 5 | 新号+新 IP+立即大量用 = 高风险组合 | 注册完直接导入即生图 | 需要**静置/养号**（注册后放 24h，或新号前 3 天低量） |
| 6 | 注册可能撞 `add-phone`（手机验证墙） | 无 SMS Provider | OpenAI 持续收紧，注册侧需前瞻接码能力 |

### 10.3 建议的落地动作（按优先级）

1. **新号第一天限产**：导入号池后当天单账号生图上限 **5 张**，`restore_at` 恢复后再放开；用号池 `limits_progress` 拦截
2. **per-account 节奏**：`_gen10_test` / 消费端加 30-90s 随机间隔 + 单账号日上限，替代 3s 连打
3. **fail-fast**：遇 `auth_invalid` / 限流类错误 → 该账号**立即标记异常停用，禁止重试**；只有 `timeout`/`server_error` 才可重试
4. **先验证 24h 静置假设**：新注册账号静置 24h 后再生图，对比"注册即打"的存活率
5. 顺带：确认远程 chatgpt2api 部署版本是否已含上游 image-429-cascade 修复（basketikun 上游 5 月提交），落后则更新

## 11. 还没生成就死：根因链与修复（2026-08-14，对比 gpt-outlook-register v0.5.5）

### 11.1 症状与证据

- 号池 jm29ce2d：`type=None`（连类型都验证不出来）、从未生图、导入即 invalid —— "还没生成就死"的直接样本
- mm9f75d4 / ne312b9c：导入时 `type=free`、quota=25 正常，但 image_gen 剩余 25（没生成过）就被标异常
- 远程出口确认：chatgpt2api 当前 `proxy_source: direct`（服务器出网经 mihomo TUN，**US/LAX**），与注册出口一致 → **排除出口不一致问题**
- 账号日志出现 `failure_code: auth_invalid, status_code: 401, account_failure: true`（gja 16 张后真死）

### 11.2 根因链（与 gpt-outlook-register v0.5.5 方案对比）

| 维度 | gpt-outlook-register v0.5.5 | 我们（修复前） | 影响 |
|------|------------------------------|----------------|------|
| 凭证 | 全量导出：session_token + access_token + **refresh_token**（Codex OAuth）+ id_token + device_id + cookie_header | 注册拿到 refresh_token 也**丢弃**（project.py 曾只记日志） | access_token 被 revoke 无恢复手段 |
| 保活 | 靠 refresh_token 换新 | chatgpt2api **原生支持** refresh_token keepalive + 刷新后重置 invalid_count，但**我们没传 RT → 该能力完全闲置** | token 短命即死 |
| add-phone 墙 | 集成 SMS 接码（SmsBower/HeroSMS），命中自动租号绑手机，**否则拿不到 refresh_token** | 无 SMS Provider；`fetch_refresh_token=true` 但命中 add-phone 时 OAuth 失败 | **最近 5 个账号 has_rt=False**，根本无 RT 可保活 |
| 错误分类 | 网络错误 ≠ 死号，release 重试 | 503 误标正常账号（dnf4c82 曾带 quota 16 被误杀） | 误杀 |
| 2FA | v0.5.3 注册后自动绑 TOTP | 无 | 账号价值/存活待验证 |

**结论**：OpenAI 对批量注册的 access_token 快速 revoke（gpt-outlook-register 自述批量**次日存活率约 2%**）。我们只存/传 access_token，被 revoke 后 chatgpt2api 无法换新 → "还没生成就死"。而**保活能力 chatgpt2api 一直就有，我们没用上**。

### 11.3 已做修复（本地）

1. `project.py`：注册成功拿到 refresh_token 时，`_save_refresh_token` 落盘 `data/keys/chatgpt_register/refresh_tokens.jsonl`（email|refresh_token，O_APPEND 原子写）
2. `data/_import_c2a2.py`：导入时读取 refresh_tokens.jsonl，`accounts` 项带 `refresh_token` 字段（chatgpt2api `AccountCreateRequest.accounts` 为 `list[dict]`，任意字段可存）
3. 导入后 chatgpt2api account-watcher 自动 keepalive（`list_refresh_token_keepalive_tokens` → `keepalive_refresh_tokens`），access_token 失效自动换新并重置 invalid

### 11.4 剩余缺口（需用户决策）

1. **add-phone 墙**：OpenAI 注册概率命中手机验证，**不绑手机拿不到 refresh_token**。修复只在"拿到 RT"时生效，命中 add-phone 的注册仍无 RT。
   - 选项 A：上 SMS 接码（SmsBower/HeroSMS，gpt-outlook-register 同款）→ 注册全程无人值守拿 RT
   - 选项 B：接受部分账号无 RT，靠数量堆（无 RT 账号仍会导入即死）
2. 错误分类：chatgpt2api 对"网络错误 vs token 无效"的区分（503 误标），后续可调
3. 2FA 绑定（v0.5.3 能力）待验证价值

### 11.5 验证方式（下一批注册后）

1. 注册日志出现 `✅ refresh_token 已保存` → refresh_tokens.jsonl 有对应行
2. 导入日志 `带 refresh_token: N 个`，号池账号 `has_rt: True`
3. 观察号池 account-watcher 日志 `keepalive N refresh tokens`，且 access_token 失效的账号自动复活（invalid 被重置）

### 11.6 实测结论（2026-08-14 晚复查，修正 §11.2/§11.4 推断）

- **RT 拿不到属常态，非我们独有**：新流程走 Codex OAuth（`app_EMoamEEZ73f0CkXaXp7hrann`）实测：choose-an-account → session/select 200 → 命中 `/add-phone`，去 `prompt` 刷新重试 2 轮仍强制绑手机，RT=0。`data/_gor_results.jsonl` 显示 gpt-outlook-register v0.5.5 实测同样全部 `has_rt: false`——它的 add-phone 破解依赖 SMS 真绑手机（`_handle_add_phone_via_sms`），我们没有接码。
- **"还没生成就死"不是新流程问题**：新流程（吸收 v0.5.5 后）注册的 5/5 账号（wv003e2a/oh86838/dqca5f4/hj041e8/ir66eb7a）导入号池全部 `status=正常 quota=25`；`ir66eb7a` 连续生成 **14 张**成功，第 15 张起 `429 insufficient_quota` → `status=限流`（约 3 小时限流窗口）。死账号（jm29ce 等 5 个）是更早旧流程批量注册（08-14 00:43 UTC）且注册后 5-8h 内被 OpenAI revoke。
- **存活模式（无 RT 前提下的正确用法）**：注册 → **立即导入号池** → **立即批量生成**，一个 3h 窗口吃满 ~14 张；3h 后限流恢复可再产（只要 access_token 未被 revoke）。账号生命周期 = revoke 前约 5-8h 窗口。
- **唯一拿 RT 的路径**是 SMS 绑手机（接码后再走 OAuth），是否上接码（SmsBower/HeroSMS 或可用的 jichisms 通道）留待用户决策。
- 号池侧修正：`data/_import_c2a2.py` 已更新 docstring（不再宣称 RT 保活）、SKIP 补入 5 个已死旧账号、修复 `call()` 解包 bug；重新运行幂等通过。
