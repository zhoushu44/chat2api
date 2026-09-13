# NVIDIA Build 注册流程步骤

> 当前正式入口为 `projects/nvidia_build/project.py`。2026-07 已完成一次有头真实页面单账号复验并取得 `nvapi-` 凭证，仅证明 L1；未经 L2/L3/L4 门禁，不据此宣称稳定、批量或 Web 真实页面量产。

---

## 步骤 1：打开 Signin 页（含 3 次重载重试）

| 项目 | 值 |
|------|-----|
| URL | `https://build.nvidia.com/?modal=signin` |
| 等待元素 | `input[name='email']` (state=visible, timeout=30s) |
| Cookie 弹窗 | `#onetrust-accept-btn-handler` → 点击 Accept All |
| 重试 | 最多 3 次（goto + 等待邮箱框；失败则重载页面） |
| 代码 | `steps/step01_open_signin.py` → `_flow.step1_open_signin(page)` |

**细节：**
- 直接URL打开signin，跳过点击Login按钮的导航竞争
- `wait_until="domcontentloaded"` 不等全量资源
- Cookie弹窗可能延迟出现，步骤2和步骤3都会检查处理

### 1.1 重载重试逻辑（关键修复）

代理模式下 `build.nvidia.com/?modal=signin` 有时只加载首页，signin 模态框不渲染（邮箱输入框不出现）。修复策略：

```python
for attempt in range(3):
    try:
        await page.goto(SIGNIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        if attempt == 2: raise
        await page.wait_for_timeout(3000); continue
    try:
        await page.wait_for_selector("input[name='email']", state="visible", timeout=30000)
        return True  # 成功
    except PlaywrightTimeoutError:
        # 模态框没加载，重载页面重试
        if attempt < 2: await page.wait_for_timeout(2000)
# 兜底：即使 timeout 也检查是否已存在
if await page.locator("input[name='email']").count() > 0: return True
return False
```

该重载逻辑用于提高弹窗出现概率；当前只确认一次单账号完整复验成功，不从单次样本推导失败率。

---

## 步骤 2：Cookie 弹窗处理

| 项目 | 值 |
|------|-----|
| 接受按钮 | `#onetrust-accept-btn-handler` (text: "Accept All") |
| 关闭按钮 | `.onetrust-close-btn-handler` |
| 遮罩检查 | `.onetrust-pc-dark-filter` |
| 代码 | `step2_accept_cookies(page)` in `rpa_nvidia.py` |

**细节：**
- 循环3次处理：点Accept → 点Close → 检查遮罩是否消失
- Cookie弹窗会在步骤3点Next前再次检查（双重保险）

---

## 步骤 3：填邮箱 + 点 Next → 导航到 NVGS 注册页

| 项目 | 值 |
|------|-----|
| 输入框 | `input[data-testid='nv-text-input-element'][name='email']` |
| Next 按钮 | `.nv-modal-content button.btn-primary.btn-lg.btn-rounded >> visible=true` |
| 导航目标 | `login.nvgs.nvidia.cn/v1/create-account?...&email=xxx&key=yyy` |
| 代码 | `step3_email_next_and_continue(page, email)` in `_flow.py` |

### 3.1 填邮箱（含弹窗恢复）
- 邮箱格式：`XXXXXXXX@zhoushu.kdns.fr`（8位随机数字）
- 生成函数：`generate_random_email()` in `_rpa.py`
- `click + type` 填入，失败时 `fill` 兜底
- 填完后 `input_value()` 校验，不匹配则重新 `fill`
- **弹窗被关恢复**：若邮箱框不可见，自动重新打开 `?modal=signin` + Cookie Accept
- 整个 step3 最多重试 3 次

### 3.2 等 Next 按钮启用
- 邮箱填入后，Next 按钮从 disabled → enabled（异步约 500ms-1s）
- 用 `page.evaluate` 检查 `button.disabled` 状态
- 最多轮询 30 次，每次间隔 500ms

### 3.3 Cookie Accept（双重保险）
- 点 Next 之前再检查一次 `#onetrust-accept-btn-handler`
- Cookie 遮罩可能挡住 Next 按钮导致点击无响应

### 3.4 点击 Next（含 expect_navigation）
- **关键问题**：页面有 2 个 Next 按钮（桌面版+移动版），Playwright strict mode 会报错
- 解决：用 `>> visible=true` 过滤不可见的移动版按钮
- 选择器：`.nv-modal-content button.btn-primary.btn-lg.btn-rounded >> visible=true`
- 兜底：Playwright locator 失败则用 JS `evaluate` 点 `.click()`
- **等待导航**：点击后用 `page.expect_navigation(wait_until="domcontentloaded")` 等页面完整刷新
- `expect_navigation` 超时不视为失败，继续轮询 URL 变化

### 3.5 等待导航
- 点击后页面完整导航（**不是** iframe/SPA 路由）
- URL 变化：`build.nvidia.com` → `login.nvgs.nvidia.cn/v1/login?...` → `login.nvgs.nvidia.cn/v1/create-account?...`
- 邮箱通过 URL 参数自动预填到 NVGS 页
- 轮询检测 URL 变化（500ms × 60次 = 最多30s）
- 导航失败时检测邮箱框是否消失（弹窗被关），消失则重开 signin 重试

### 3.6 等注册表单
- 同时等 `#registration_password` 或 `#loginNextButton`（两个都接受）
- 如果先到 identifier 页（旧流程），点 `#loginNextButton` 再到 create-account
- 如果直接到 create-account（新流程），直接继续
- 超时未出现则重试整个 step3

### 3.7 踩坑：邮箱好像要输两次
- **现象**：build 模态已填邮箱并点 Next，到 NVGS 仍停在标识页 / 邮箱框空 / 需再输一次
- **原因**：URL 常带 `email=`，但 `#loginNextButton` 前输入框可能仍为空；旧逻辑只点 Next 不保证已填
- **修复**：`_ensure_nvgs_email_filled`（`_flow.py`）在 identifier 点 Next 前校验并补填；create-account 若仍有空邮箱框则可选补填；build 模态多框时优先可见框并校验 `input_value`
- **正式路径**：`projects/nvidia_build/steps/_flow.py`

---

## 步骤 6：填密码

| 项目 | 值 |
|------|-----|
| 输入框 | `#registration_password` |
| 密码值 | `zs1236547.`（定义在 `rpa_nvidia.py` PASSWORD 变量） |
| 代码 | `step6_input_password(page)` in `rpa_nvidia.py` |

---

## 步骤 7：填确认密码

| 项目 | 值 |
|------|-----|
| 输入框 | `#registration_passwordConfirm` |
| 代码 | `step7_input_confirm_password(page)` in `rpa_nvidia.py` |

---

## 步骤 8：勾选同意条款

| 项目 | 值 |
|------|-----|
| 数据协议 | `#data_general_agreement-input` (type=checkbox, hidden) |
| 条款协议 | `#terms_and_conditions-input` (type=checkbox, hidden) |
| 代码 | `step8_check_agreement(page)` in `rpa_nvidia.py` |

**细节：**
- Angular Material 自定义 checkbox，`<input>` 元素被隐藏在自定义组件后面
- Playwright `click()` 会因 not visible 超时
- 解决：用 JS `document.getElementById('xxx').click()` 直接点击 hidden input
- 兜底：JS 失败则 Playwright `locator.click(force=True)`

---

## 步骤 9：CaptchaRun API 解 hCaptcha

| 项目 | 值 |
|------|-----|
| API 基址 | `https://api.captcha-run.com/v2/tasks` |
| Auth | `Authorization: Bearer {CAPTCHARUN_KEY}` |
| 创建任务 | POST `{captchaType: "HCaptcha", siteKey, siteReferer}` |
| 轮询结果 | GET `/v2/tasks/{taskId}` (间隔3s, 最多60次=180s) |
| 代码 | `step9_captcharun_solve(page)` in `test_captcharun.py` |

### 9.1 提取 sitekey
三种方式（依次尝试）：
1. `document.querySelector('[data-sitekey]').getAttribute('data-sitekey')`
2. `iframe[src*="hcaptcha"]` → 从 src 正则匹配 `sitekey=xxx`
3. `hcaptcha.getConfig().sitekey`
4. 兜底：遍历 `page.frames` 找 hcaptcha iframe

### 9.2 siteReferer
- 取自 create-account 页的 origin: `https://login.nvgs.nvidia.cn/`

### 9.3 创建任务
```json
{
  "captchaType": "HCaptcha",
  "siteKey": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "siteReferer": "https://login.nvgs.nvidia.cn/",
  "fallbackToActualUA": true
}
```

### 9.4 轮询
- 响应 `status=Working` → 继续轮询
- 响应 `status=Fail` → 返回 None
- 响应其他 → 检查 `response.gRecaptchaResponse` 提取 token
- 每次间隔 3 秒，最多 60 次（180 秒超时）

---

## 步骤 10：注入 hCaptcha Token

| 项目 | 值 |
|------|-----|
| 代码 | `step10_inject_token(page, token)` in `test_captcharun.py` |

### 注入方式（三重保障）

**方式 1：postMessage 注入**
- 模拟 hCaptcha iframe 发 `challenge-passed` 事件
- 找到所有 `iframe[data-hcaptcha-widget-id]`
- 对每个 iframe 触发 `window.dispatchEvent(new MessageEvent('message', ...))`

**方式 2：调用 render callback**
- `_setup_hcaptcha_route` 在 Worker 初始化时拦截了 hCaptcha api.js
- 注入的 hook 代码捕获 `hcaptcha.render(container, {callback: fn})` 的 callback
- 存入 `window.__hcaptcha_callbacks[]`
- 步骤10 直接调用 `callbacks[i](token)`
- 同时设 `[name="h-captcha-response"].value = token` + `[data-hcaptcha-response]`
- 检查 Angular form control 状态：`captchaEl.classList.contains('ng-valid')` + `#register_button.disabled`

**方式 3：hcaptcha 全局对象**
- `hcaptcha.setValue(widgetId, token)`
- `hcaptcha.setResponse(token)`
- `hcaptcha.getResponse = function() { return token; }`
- `hcaptcha.execute = function() { return Promise.resolve(token); }`

**兜底：手动设 Angular 状态**
- 设 `[name="h-captcha-response"].value = token` + dispatch input/change 事件
- 设 `data-hcaptcha-response` 属性
- 手动修改父 div 的 class: `ng-invalid` → `ng-valid`, `ng-untouched` → `ng-dirty ng-touched`

### hCaptcha Hook 注入原理（_setup_hcaptcha_route）
```
浏览器请求 hcaptcha/api.js
  → Playwright route.intercept() 拦截
  → 在代码开头注入 hook:
     var _origRender = Ogre.render;
     Ogre.render = function(a, b) {
       window.__hcaptcha_callbacks.push(b.callback);
       window.__hcaptcha_widget_config = b;
       return _origRender.call(this, a, b);
     };
  → 返回修改后的 JS 给浏览器
  → ng-hcaptcha 组件调用 hcaptcha.render() 时，callback 被捕获
```

---

## 步骤 11：点击创建账户

| 项目 | 值 |
|------|-----|
| 按钮 | `#register_button` |
| 等待 | `wait_for(state="visible", timeout=10s)` + 等按钮 enabled |
| 导航目标 | NVGS profile-complete 页（邮箱验证页） |
| 代码 | `step11_click_create_account(page)` in `test_captcharun.py` |

**细节：**
- 注入 token 后按钮异步从 disabled → enabled（最多等10s）
- 点击后等待 URL 包含 `profile-complete` 或者出现 `input[maxlength='1']`

**踩坑（2026-08 L4 验收）：**
- NVIDIA 服务端偶发返回 `.../v1/error?...jarvis_error=%7B%22error%22:%22SERVICE_UNAVAILABLE%22%7D`。step11 旧代码只判"URL 变了"便标 `OK=true`，导致 step12 在 error 页空等 `mail_timeout` 秒后才 FAIL。
- 现 step11 在"点击后等待跳转"后增 `urlparse` 检查：若 `parsed.path` 含 `/v1/error`，step11 直接 `return False`（`failure_class=step_returned_false`），由 dbg.fail 写证据，避免 step12 空耗一个邮箱超时窗口。
- 此分支是 NVIDIA 服务端抖动（频率 <10%），重跑任务即可成功；不属项目代码问题。

---

## 步骤 12：邮箱验证码

| 项目 | 值 |
|------|-----|
| 页面 URL | `login.nvgs.nvidia.cn/v1/profile-complete?...` |
| OTP 输入 | `input[maxlength='1']` × 6 个单格输入框 |
| 继续按钮 | `button:has-text('继续'):visible` |
| 验证码来源 | 共用 `cloudflare_worker` Provider（CloudMail 优先） |
| 代码 | `steps/step12_verify_email.py` |

### 12.1 获取验证码

1. NVIDIA 发验证邮件到 Provider 生成的地址。
2. `CloudflareWorkerEmailProvider` 调用已配置的 CloudMail 收件接口轮询邮件。
3. 邮件正文会先进行 quoted-printable 解码，再优先提取 `verification code is`
   后的六码验证码，支持 `123-456` 格式。
4. 未配置 CloudMail 时，Provider 才使用已配置的 Worker/KV 字段作为兼容兜底。
5. 默认轮询超时 120 秒；所有邮箱配置由全局 `email.cloudflare_worker` 统一管理。

### 12.2 填入 OTP
- 6位验证码逐格填入 `input[maxlength='1']`（`fill` + `input`/`change` 事件，Angular 兼容）
- Continue 仍 `disabled` 时：JS 强制启用并点击；仍停在 `profile-complete` 时重试填码+提交
- **成功条件**：必须离开 `profile-complete`（进入 consent / build 等）；仍停在 OTP 页或 `chrome-error://` → `return False`（禁止假成功）
- 日志用 `_safe_print`：Windows GBK 控制台避免页面 `\xa0` 触发 `UnicodeEncodeError`

### 12.3 解析保护
NVIDIA HTML 邮件含有收件地址、发件头和 CSS 色值等无关数字。Provider 只在验证码提示附近
提取明确的六码 OTP，避免把邮箱地址或样式中的数字误填入页面。

### 12.4 踩坑（2026-07）
- 并发下偶发 OTP 未吃进 Angular：点 Continue 后 URL 仍是 `profile-complete`，旧逻辑仍 `return True` → step13 落到 `chrome-error` / `no_key`。已改为「离开 profile-complete 才算 step12 成功」。

### 12.5 验证码无效重试（2026-08 L4 验收踩坑）
- 偶发：mailnest 取到 code（24s 内）→ step12 填提交 → NVIDIA 服务端返回「验证码无效」提示（`.notice-alert` + 标题"验证码无效"），但 step12 没识别仍等满 20 次循环后 FAIL。
- 修复：step12 在等待跳出 profile-complete 循环中新增分支——
  1. 检测 `body.innerText` 含"验证码无效" 且 `.notice-alert` 存在；
  2. 点"重新请求新验证码"链接（`a:has-text` 命中 `重新请求|resend|request new code`）；
  3. 把上一次的 code 加入 `used_codes`，作为 `skip_codes` 调 `cf_fetch_code`（注入器 `sync_fetch_safe` 透传到 `ctx.email.wait_code(skip_codes=...)`，mailnest `_wait_code_sync` 已支持）；
  4. 拿到不同 code 后清空已填 OTP 输入框再 `_fill_and_submit`；
  5. 最多 1 次重试（`retried_for_invalid=True` 后不再触发）。
- mailnest 已支持 `skip_codes`（`_wait_code_sync` 用 `skip = {str(c).strip() for c in (skip_codes or ()) if c}` 过滤已见过的旧码）。

---

## 步骤 13：Consent + 中间页 + API Key 提取

| 项目 | 值 |
|------|-----|
| 代码 | `step13_fetch_apikey(page, email)` in `test_captcharun.py` |

### 13.1 Consent 页
- URL: `static-login.nvidia.com/service/default/noir/consent/developer/v1-1?...`
- 内容: "快完成了！请确认以下信息以完成注册"
- 操作:
  1. 勾选 2 个 checkbox（推荐设置 + 开发者新闻）
  2. 点"提交"按钮 (`button.button-cta:visible`)

### 13.2 等待回调跳转（循环 60 次，每次 1.5s = 最多 90s）

Consent 提交后，页面经过 0-2 个中间页最终跳到 `build.nvidia.com`。

#### 中间页 A：密码登录页
- URL 特征: `/login/password` 或 `/login/identifier` 或 `/login/`
- 来源: `login.nvgs.nvidia.cn/v1/login/password?...`
- 操作（JS 一次性加速）:
  ```javascript
  // 填邮箱（如果为空）
  document.querySelector("input[name='email']").value = email;
  // 填密码
  document.querySelector("input[type='password']").value = PASSWORD;
  // dispatch input/change 事件
  // 点提交按钮
  document.querySelector("button.btn-primary").click();
  ```
- 只处理一次 (`pwd_done = True`)

#### 中间页 B：Select-Account / Cloud Accounts 页
- URL: `cloudaccounts.nvidia.com/sf/v2/select-account?...&can_create=true&accounts=W10&count=0`
- 含义: 需要创建 NVIDIA Cloud Account（新注册用户无已有账户）
- 操作:
  1. 输入账户名称: `input[data-testid='kui-text-input-element'][name='name']` → 填 `"11"`
  2. 等 800ms 让 Create 按钮启用（填入名称前按钮 disabled）
  3. 点击: `button:has-text('Create NVIDIA Cloud Account'):visible`
  4. 创建后自动跳转到 `build.nvidia.com`
- 只处理一次 (`sa_done = True`)

### 13.3 确保在 build.nvidia.com
- 如果没跳到 build.nvidia.com → `page.goto("https://build.nvidia.com/")`
- 等 `domcontentloaded` + 4s 延迟

### 13.4 NGC API 两步获取 Key（page.evaluate）

**Step 1: 获取 orgName**
```javascript
const r1 = await fetch('https://api.ngc.nvidia.com/user-context', {
  method: 'GET',
  credentials: 'include',
  headers: { accept: 'application/json, text/plain, */*' }
});
const d1 = await r1.json();
const orgName = d1.orgName;
```

**Step 2: 创建 API Key**
```javascript
const url2 = `https://api.ngc.nvidia.com/v3/orgs/${orgName}/keys/type/AI_PLAYGROUNDS_KEY`;
const payload = {
  expiryDate: '2126-04-08T07:00:00Z',   // 100年有效期
  name: 'dev',
  type: 'AI_PLAYGROUNDS_KEY',
  policies: [{
    product: 'nv-cloud-functions',
    scopes: ['invoke_function'],
    resources: [{ id: '*', type: 'account-functions' }]
  }]
};
const r2 = await fetch(url2, {
  method: 'POST',
  credentials: 'include',
  headers: { accept: '*/*', 'content-type': 'application/json' },
  body: JSON.stringify(payload)
});
const d2 = await r2.json();
// API Key = d2.key.value (格式: "nvapi-xxxx...")
```

**提取逻辑：**
- 优先: `d2.key.value`
- 兜底: `d2.apiKey.value`
- 返回 API Key 字符串或 None

### 13.5 保存结果

> **现行控制台规则：**经共用 `TaskRunner` 运行时，结果由其统一写入全局 `ui.keys_output_dir`。该值是文件夹（不要填写文件名），支持绝对路径或相对仓库根目录的路径；留空为 `data/keys/nvidia_build/api_keys.txt`，非空为 `<文件夹>/nvidia_build_api_keys.txt`，目录自动创建，控制台预览读取同一位置。格式为 `email|apikey`。本节下方的 `save_key` 与 `api_keys.txt` 是旧独立脚本保存行为，仅供过渡参考，不能代表控制台。

- `save_key(email, apikey)` → 追加到 `api_keys.txt`（旧独立脚本）
- 格式: `{email}\t{apikey}\n`（旧独立脚本）

---

## 浏览器底座（2026-07 实测）

| 配置 | 值 |
|------|-----|
| 解析 | `resolve_browser_backend(config, project_id="nvidia_build")` → 显式参数 / `projects.nvidia_build.browser_backend` / `browser.backend` / 默认 `playwright` |
| 可选值 | `playwright` · `patchright`（免费；需 `pip install patchright`） |
| 入口 | `project.py` 传给共用 `browser_session(..., browser_backend=...)` |
| 当前确认 | `patchright` 可由同一入口选择；本次文档同步只确认一次单账号真实复验成功，不沿用旧批量数据作为当前成熟度结论 |

**踩坑：** 只 import `resolve_browser_backend` 而不传给 `browser_session` 时，UI 切换无效；必须显式 `browser_backend=`。

---

## 主流程与批量循环

脚本支持两种运行模式：**单独模式**（concurrency=1，串行）和**并发模式**（concurrency≥2，多账号同时）。两种模式共用同一个 `run_one_account()`，仅调度方式不同。

### 单账号流程 (run_one_account) — 两种模式共用

```python
steps = [
    step1_open_signin(page),         # 打开 signin（含3次重载重试）
    step2_accept_cookies(page),       # Cookie
    step3_email_next_and_continue(),  # 邮箱→Next→NVGS注册页（Next优先于Cookie）
    step6_input_password(page),       # 密码
    step7_input_confirm_password(),   # 确认密码
    step8_check_agreement(page),      # 同意条款
]
# 任何步骤失败 → return {status: "fail_step{i}"}
# step3 失败时特殊重试：重新 step1+step2+step3，最多 2 次
step9  → CaptchaRun 解 hCaptcha（失败 → "fail_captcha"）
step10 → 注入 token
step11 → 点创建账户
step12 → 邮箱验证
step13 → 取 API Key
```

### step3 失败重试逻辑

```python
if not success and i == 3:
    print(f"[{idx}] 步骤3失败, 重试: 重新打开 signin 页...")
    for _retry in range(2):
        try:
            await step1_open_signin(page)
            await step2_accept_cookies(page)
            success = await step3_email_next_and_continue(page, email)
            if success:
                print(f"[{idx}] 步骤3重试第{_retry+1}次成功")
                break
        except Exception as e2:
            print(f"[{idx}] 步骤3重试异常: {e2}")
```

### 模式一：单独模式（concurrency=1，默认）

串行执行，一个账号跑完再跑下一个。`Semaphore(1)` 等价于互斥锁，`stagger` 被忽略（无意义）。

**调用**：`python test_captcharun.py <total> <start> 1 0`

```python
# concurrency=1 时实际行为：
# 账号 #start → run_one_account → 完成 → 账号 #(start+1) → ...
# 无并发、无 stagger 错开
for idx in range(start, end+1):
    r = await run_one_account(idx, end)
    save_key(r["email"], r["apikey"])
```

**适用**：调试、首次跑通流程、低风控环境、单账号验证。

### 模式二：并发模式（concurrency≥2，需通过 L2 后再按 L3 门禁验收）

```python
# 命令行参数: total start concurrency stagger
total = int(args[0])           # 总账号数
start = int(args[1])           # 起始编号
concurrency = int(args[2])     # 并发数（推荐 8）
stagger = int(args[3])         # 启动间隔秒数（推荐 2）

sem = asyncio.Semaphore(concurrency)   # 并发限制
file_lock = asyncio.Lock()              # 文件写入锁（避免并发写 api_keys.txt 错乱）
progress_lock = asyncio.Lock()          # 进度统计锁（避免日志交错错乱）

async def run_with_sem(idx):
    # 错开启动：第 N 个账号延迟 (N-start)*stagger 秒，避免同时注册触发 NVIDIA 风控
    if stagger > 0 and idx > start:
        delay = (idx - start) * stagger
        print(f"[{idx}] 错开启动, 等待 {delay}s ...")
        await asyncio.sleep(delay)
    async with sem:
        try:
            r = await run_one_account(idx, end)
            async with file_lock:           # 写文件加锁
                save_key(r["email"], r["apikey"])
        except Exception as e:
            r = {"email": "", "apikey": None, "status": f"exception: {e}"}
        async with progress_lock:           # 进度统计加锁
            counter["done"] += 1
            if r.get("apikey"):
                counter["ok"] += 1
                print(f"[{idx}] [OK] ... 累计成功 {counter['ok']} 个")
            else:
                print(f"[{idx}] [SKIP] status={r.get('status')}")

# 所有账号同时创建任务，由 Semaphore 控制实际并发数
tasks = [asyncio.create_task(run_with_sem(idx)) for idx in range(start, end + 1)]
await asyncio.gather(*tasks)
```

**关键机制**：
- `asyncio.Semaphore(concurrency)` — 限制同时运行的账号数为 concurrency
- `asyncio.Lock()` (file_lock) — 保护 api_keys.txt 写入（多个账号同时成功时序列化写）
- `asyncio.Lock()` (progress_lock) — 保护进度日志输出
- `stagger` 错开 — 第 N 个账号启动前 sleep `(N-start)*stagger` 秒

**适用**：仅用于通过 L2 后的 L3 验收；并发参数应从 2 逐级提高，不预设已可生产。

### 代理模式

代理统一由共用 `socks5` Provider 提供。在控制台输入 `socks5://host:port` 或带认证链接，也可配置动态代理 API；留空表示直连。NVIDIA 正式页面固定使用有头浏览器，控制台不显示无效的 headless 选项。

---

## 关键配置汇总

| 配置项 | 文件 | 值 |
|--------|------|-----|
| 密码 | `projects.nvidia_build.password` | 控制台项目配置 |
| CaptchaRun Key | `captcha.hcaptcha.captcharun.api_key` | Provider 配置 |
| CloudMail | `email.cloudflare_worker` | 全局共享 Provider 配置 |
| Keys 输出文件 | `ui.keys_output_dir` | 留空时为 `data/keys/nvidia_build/api_keys.txt` |

---

## 各页面 URL 与关键元素速查表

| 页面 | URL 模式 | 关键选择器 |
|------|----------|-----------|
| Signin | `build.nvidia.com/?modal=signin` | `input[name='email']`, `.nv-modal-content button.btn-primary >> visible=true` |
| Cookie | (同上) | `#onetrust-accept-btn-handler` |
| 注册表单 | `login.nvgs.nvidia.cn/v1/create-account` | `#registration_password`, `#registration_passwordConfirm`, `#data_general_agreement-input`, `#terms_and_conditions-input`, `#register_button` |
| hCaptcha | (iframe in 注册表单) | `iframe[src*="hcaptcha"]`, `[data-sitekey]`, `[name="h-captcha-response"]` |
| 邮箱验证 | `login.nvgs.nvidia.cn/v1/profile-complete` | `input[maxlength='1']` (×6), `button:has-text('继续')` |
| Consent | `static-login.nvidia.com/.../consent/...` | `input[type="checkbox"]`, `button.button-cta` |
| 密码登录 | `login.nvgs.nvidia.cn/v1/login/password` | `input[type='password']`, `button.btn-primary` |
| Select-Account | `cloudaccounts.nvidia.com/sf/v2/select-account` | `input[data-testid='kui-text-input-element'][name='name']`, `button:has-text('Create NVIDIA Cloud Account')` |
| 首页(已登录) | `build.nvidia.com/` | (NGC API 调用) |

---

## 时间线（历史流程顺序示例，不作为当前吞吐结论）

```
0s    获取免密 SOCKS5 代理 IP (∼1s)
1s    打开 signin 页（含可能的1次重载，∼3-5s）
5s    Cookie 处理 (∼1s)
6s    填邮箱 + 点 Next + 导航到 NVGS (∼3s)
9s    填密码/确认/勾选 (∼3s)
12s   CaptchaRun 解 hCaptcha (∼15s)
27s   注入 token + 点创建账户 (∼2s)
29s   等邮件 + CF Worker 提验证码 + 填 OTP (∼8s)
37s   Consent 勾选+提交 (∼3s)
40s   密码登录页 (JS加速, ∼3s)
43s   Select-Account 填名+创建 (∼3s)
46s   跳到 build.nvidia.com + NGC 取 Key (∼5s)
51s   完成！拿到 API Key
```

以上时间线仅作流程顺序参考；当前单账号复验不能推导并发吞吐或批量耗时。
