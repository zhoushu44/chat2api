# NVIDIA 注册流程 - 实际 URL 和字段（从 browser 模式分析）

## 📊 从 browser 模式代码分析出的关键信息

### 1. 页面 URL

```python
# Step 1: 打开 signin 页
SIGNIN_URL = "https://build.nvidia.com/?modal=signin"
```

### 2. 邮箱提交流程（Step 3）

```python
# 行为：填邮箱 → 点 Next → 跳转到 NVGS
# 实际跳转 URL:
# https://login.nvidia.com/v1/create-account?email=xxx&key=yyy

# 关键观察：
# - 邮箱提交后直接导航到 NVGS 域
# - URL 包含 email 和 key 参数
# - key 参数从 build.nvidia.com 页面获取
```

### 3. 注册表单字段（Step 6-11）

```python
# NVGS create-account 页的表单字段：
form_data = {
    "registration_password": password,        # 密码输入框 #registration_password
    "data_general_agreement": "on",           # 同意条款 checkbox
    "h-captcha-response": hcaptcha_token,     # hCaptcha token
}

# 注意：
# - email 已预填（从 URL 参数）
# - 确认密码可能在前端校验，无需独立字段
# - 提交按钮：#register_button
```

### 4. OTP 验证（Step 12）

```python
# 页面：login.nvidia.com/v1/profile-complete
# OTP 输入框：input[maxlength='1'] (6 个单格)
# 提交按钮：Continue / Verify
# 提交后跳转到：consent.nvidia.com

# 可能的 OTP 提交端点：
# POST https://login.nvidia.com/v1/otp/verify
# Body: {"email": email, "code": code}
```

### 5. Post-Verification 流程（Step 13）

```python
# 1. consent.nvidia.com
#    - 勾选同意条款 checkbox
#    - 点 Accept/Submit

# 2. login.nvidia.com/login/password
#    - identifier 页：填邮箱 + Next
#    - password 页：填密码 + Sign In

# 3. cloudaccounts.nvidia.com/select-account
#    - 输入云账户名称："11"
#    - 点 Create

# 4. 回调到 build.nvidia.com
#    - login.nvidia.com/callback/nca_picker
#    - 最终到 build.nvidia.com
```

### 6. NGC API 调用（Step 13）

```python
# 1. 获取 user-context
GET https://api.ngc.nvidia.com/user-context
Response: {"orgName": "xxx"}

# 2. 创建 API Key
POST https://api.ngc.nvidia.com/v3/orgs/{orgName}/keys/type/AI_PLAYGROUNDS_KEY
Body: {
    "expiryDate": "2126-04-08T07:00:00Z",
    "name": "dev",
    "type": "AI_PLAYGROUNDS_KEY",
    "policies": [...]
}
Response: {"result": {"apiKey": {"value": "nvapi-xxx"}}}
```

### 7. hCaptcha sitekey

```python
# 从 _flow.py step9 提取：
sitekey = "042b0b36-8bec-465e-a529-7c52a1c8d7d5"
```

## 🔧 HTTP 引擎更新建议

基于以上分析，HTTP 引擎应该：

### 方案 A: 直接构造 URL（推荐）

```python
def submit_email(self, email: str):
    # 直接访问 NVGS create-account
    # 不需要 POST 提交邮箱，直接跳转
    redirect_url = f"{NVGS_BASE}/v1/create-account?email={email}"
    
    response = self._session.request(
        method="GET",
        url=redirect_url,
        headers=self._base_headers(),
        allow_redirects=True,
    )
    
    return response.status_code == 200, "", redirect_url
```

### 方案 B: 模拟完整流程

```python
# 1. 访问 build.nvidia.com 获取 key
response = self._session.get(SIGNIN_URL)
key = extract_key_from_html(response.text)

# 2. 跳转到 NVGS
redirect_url = f"{NVGS_BASE}/v1/create-account?email={email}&key={key}"
response = self._session.get(redirect_url)

# 3. 提交注册表单
form_data = {
    "registration_password": password,
    "data_general_agreement": "on",
    "h-captcha-response": hcaptcha_token,
}
response = self._session.post(
    f"{NVGS_BASE}/v1/create-account",
    data=form_data
)

# 4. 提交 OTP
otp_data = {"email": email, "code": code}
response = self._session.post(
    f"{NVGS_BASE}/v1/otp/verify",
    json=otp_data
)

# 5. Post-Verification 流程
# ...（见 handle_post_verification 方法）

# 6. 获取 API Key
# ...（见 fetch_api_key 方法）
```

## ⚠️ 需要验证的部分

1. **key 参数提取方式**
   - 位置：build.nvidia.com 页面的 JS 变量
   - 可能：`window.__INITIAL_STATE__.key` 或 meta 标签

2. **OTP 提交端点**
   - 假设：`/v1/otp/verify`
   - 需要验证实际端点

3. **Post-Verification 流程**
   - consent 页的表单结构
   - 密码登录的实际端点
   - 云账户创建的 API

## 📋 下一步

1. **运行 browser 模式一次**
   ```bash
   python projects/nvidia_build/test_one_account.py
   ```

2. **观察浏览器 DevTools → Network**
   - 记录所有 POST/GET 请求
   - 记录请求 URL、方法、字段

3. **更新 HTTP 引擎**
   ```python
   # 编辑 projects/nvidia_build/steps/_http_engine.py
   # 根据实际抓包结果更新 URL 和字段
   ```

4. **测试 HTTP 模式**
   ```bash
   python projects/nvidia_build/test_http_simple.py
   ```

---

**分析日期**: 2026-08-03  
**来源**: 从 _flow.py 和 _rpa.py 代码分析
