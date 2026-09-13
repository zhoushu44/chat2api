# [OPEN] 并发疑似假并发调试记录

## 症状
用户反馈当前并发好像是“假并发”，需要确认任务是否真正同时执行。

## 调试会话
- session_id: `fake-concurrency`
- 阶段: 证据收集
- 业务逻辑修改: 尚未进行

## 可证伪假设
1. 任务接口接收 `concurrency`，但执行层实际按串行循环处理。
2. 多个 worker 已创建，但被全局锁、浏览器复用或 Provider 锁串行化。
3. UI/API 传入的并发参数被覆盖为 `1`，或只影响任务数量而非同时运行数。
4. 实际存在重叠执行，但日志/状态刷新顺序化，造成假并发观感。
5. worker 池存在，但邮箱、验证码或代理共享资源使关键步骤串行阻塞。

## 观测计划
- 查找任务创建、并发参数解析、worker 调度和项目执行入口。
- 只增加运行时观测，不先修改业务逻辑。
- 复现后用 worker/task 的开始、结束时间和活动数判断真实重叠。

## 已加入观测
- `core/task_runner.py` 在每个账号进入/退出 semaphore 后记录 `account_enter`、`account_exit`、`active` 和耗时。
- 这一步未改变调度策略，仅用于确认同一时刻实际执行中的账号数。

## 证据与根因

### 根因 1：MailNest `wait_code` 全局锁串行化所有取码（最大瓶颈）
- `mailsys/mailnest/provider.py:416-418`：`async with self._lock` 包住整个 `wait_code`。
- `_wait_code_sync` 内部每 3s 轮询一次，最长等 `mail_timeout=180s`。
- concurrency=5 时 5 个账号**排队**等码：5×30s=150s 而非 30s 并行。

### 根因 2：`register_lite` 同步 HTTP 直接阻塞事件循环
- `projects/grok_register/steps/_lite_engine.py` 中 `c.visit_home()`、`c.load_signup_page()`、
  `c.create_email_validation_code()`、`c.verify_email_validation_code()`、`c.create_account()`、
  `c.fetch_sso_token()` 全是 curl_cffi 同步调用，直接在 async 函数里执行。
- 每个调用阻塞整个事件循环 1-5s，期间其他 4 个账号完全停滞。
- `c.fetch_sso_token` 内部还有 `time.sleep(2.0 * (attempt+1))` 阻塞重试。
- `project.py:25` 的 `ctx.email.generate_address()` 也是同步调用，同样阻塞。

### 根因 3：`stagger` 按序号累计，不是按并发窗口错开
- `core/task_runner.py:192-195`：`delay = (idx - config.start) * config.stagger`
- stagger=5 时：账号 5 等 20s，账号 10 等 45s，账号 100 等 **495s** 才启动。
- 即使 concurrency=5，第一批 5 个账号也要 0/5/10/15/20s 依次启动。

## 修复

| 根因 | 文件 | 修复 |
|------|------|------|
| 1 | `mailsys/mailnest/provider.py` | 移除 `wait_code` 的 `async with self._lock`；`to_thread` 已隔离阻塞，不同邮箱 key 互不冲突 |
| 2 | `projects/grok_register/steps/_lite_engine.py` | 所有 `c.*()` 同步调用包 `await asyncio.to_thread(...)` |
| 2 | `projects/grok_register/project.py` | `generate_address` 包 `await asyncio.to_thread(...)` |
| 3 | `core/task_runner.py` | stagger 改为 `(idx-start) % concurrency * stagger`，按并发槽位错开 |

### 其他邮箱 Provider 同样问题（未修，当前 grok 用 mailnest）
- `mailsys/tempmail/provider.py:272`：`async with self._lock`
- `mailsys/xunmail/provider.py:337`：`async with self._lock`
- `mailsys/cloudflare_worker/provider.py`：无锁，无此问题

## 观测点（仍保留）
- `core/task_runner.py` 的 `account_enter`/`account_exit` 日志用于验证修复效果。

---

## 第二轮：全项目修复

### 邮箱 Provider 锁（全部移除）
| 文件 | 修复 |
|------|------|
| `mailsys/tempmail/provider.py` | `wait_code` 和 `wait_link` 移除 `async with self._lock` |
| `mailsys/xunmail/provider.py` | `wait_code` 移除 `async with self._lock` |
| `mailsys/cloudflare_worker/provider.py` | 无锁，无需修改 |

### chatgpt_register
| 文件 | 修复 |
|------|------|
| `projects/chatgpt_register/project.py` | `generate_address` 包 `await asyncio.to_thread(...)` |
| `projects/chatgpt_register/steps/_http_engine.py` | 已确认 `_register_sync` 通过 `asyncio.to_thread` 调用，内部 sync HTTP 不阻塞事件循环 |
| `projects/chatgpt_register/steps/_sentinel.py` | 全部 async，无阻塞调用 |

### nvidia_build
| 文件 | 修复 |
|------|------|
| `projects/nvidia_build/project.py` | `generate_address` 包 `await asyncio.to_thread(...)` |
| `projects/nvidia_build/steps/_hybrid_engine.py` | 38 处 `session.get/post/put` 同步调用包 `await asyncio.to_thread(...)` |
| `projects/nvidia_build/steps/_hybrid_engine.py:798` | `_time.sleep(2)` 改为 `await asyncio.sleep(2)` |
| `projects/nvidia_build/steps/_hybrid_engine.py:861` | `.text` 链式调用加括号修正 |

### task_runner（第一轮已修）
| 文件 | 修复 |
|------|------|
| `core/task_runner.py:193` | stagger 改为 `(idx-start) % concurrency * stagger` |
