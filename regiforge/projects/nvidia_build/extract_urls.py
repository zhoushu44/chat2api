"""NVIDIA HTTP 模式 - 实际 URL 和字段提取工具

用法：
1. 先用 browser 模式跑一次（手动或自动）
2. 观察网络请求，记录关键 URL 和字段
3. 更新此文件中的配置
4. 运行 HTTP 模式测试
"""

# ============ 从 browser 模式抓包得到的实际配置 ============

# 1. build.nvidia.com 的 key 参数（从 modal=signin 页面提取）
# 位置：页面 JS 变量或 meta 标签
# 示例：window.__INITIAL_STATE__ = {key: "xxx"}
BUILD_KEY = None  # 需要抓包获取

# 2. 邮箱提交的实际 URL
# browser 模式观察：填邮箱 → 点 Next → 跳转到 NVGS
# 实际行为：可能是前端直接跳转，不需要 POST
EMAIL_SUBMIT_URL = None  # 可能不需要，直接跳转

# 3. NVGS create-account 页的表单字段
# 从 _flow.py step3 观察：
# - 到 create-account 页后，邮箱已预填
# - 需要填：registration_password, data_general_agreement, h-captcha-response
# - 提交到：POST /v1/create-account 或当前 URL
REGISTRATION_FIELDS = {
    "email": None,  # 预填
    "registration_password": "{password}",
    "registration_passwordConfirm": "{password}",
    "data_general_agreement": "on",
    "h-captcha-response": "{hcaptcha_token}",
}

# 4. OTP 提交的实际 URL
# 从 _flow.py step12 观察：
# - profile-complete 页
# - OTP 输入框：input[maxlength='1']
# - 提交按钮：Continue
# - 提交后跳转到 consent.nvidia.com
OTP_SUBMIT_URL = "https://login.nvidia.com/v1/otp/verify"  # 假设，需要验证

# 5. Post-Verification 流程
# 从 _flow.py step13 观察：
# - consent.nvidia.com: 勾选同意条款 → 点 Accept
# - login.nvidia.com/login/password: 填邮箱 + Next → 填密码 + Sign In
# - cloudaccounts.nvidia.com/select-account: 输入 "11" → 点 Create
# - 回调到 build.nvidia.com
CONSENT_URL = "https://consent.nvidia.com/"
LOGIN_IDENTIFIER_URL = "https://login.nvidia.com/v1/login/identifier"
LOGIN_PASSWORD_URL = "https://login.nvidia.com/v1/login/password"
CLOUD_ACCOUNT_URL = "https://cloudaccounts.nvidia.com/api/v1/accounts"
NCA_PICKER_CALLBACK = "https://login.nvidia.com/callback/nca_picker"

# 6. NGC API 的实际端点（从 _flow.py step13 观察）
# - GET https://api.ngc.nvidia.com/user-context
# - POST https://api.ngc.nvidia.com/v3/orgs/{orgName}/keys/type/AI_PLAYGROUNDS_KEY
NGC_USER_CONTEXT_URL = "https://api.ngc.nvidia.com/user-context"
NGC_CREATE_KEY_URL = "https://api.ngc.nvidia.com/v3/orgs/{org_name}/keys/type/AI_PLAYGROUNDS_KEY"

# ============ 使用示例 ============

if __name__ == "__main__":
    print("=" * 60)
    print("NVIDIA HTTP 模式 - URL 和字段配置")
    print("=" * 60)
    print("\n需要从 browser 模式抓包获取以下信息：")
    print(f"1. BUILD_KEY: {BUILD_KEY or '需要抓包'}")
    print(f"2. EMAIL_SUBMIT_URL: {EMAIL_SUBMIT_URL or '可能不需要，直接跳转'}")
    print(f"3. REGISTRATION_FIELDS: {REGISTRATION_FIELDS}")
    print(f"4. OTP_SUBMIT_URL: {OTP_SUBMIT_URL or '需要验证'}")
    print(f"5. Post-Verification URLs:")
    print(f"   - CONSENT_URL: {CONSENT_URL}")
    print(f"   - LOGIN_IDENTIFIER_URL: {LOGIN_IDENTIFIER_URL}")
    print(f"   - LOGIN_PASSWORD_URL: {LOGIN_PASSWORD_URL}")
    print(f"   - CLOUD_ACCOUNT_URL: {CLOUD_ACCOUNT_URL}")
    print(f"   - NCA_PICKER_CALLBACK: {NCA_PICKER_CALLBACK}")
    print(f"6. NGC URLs:")
    print(f"   - NGC_USER_CONTEXT_URL: {NGC_USER_CONTEXT_URL}")
    print(f"   - NGC_CREATE_KEY_URL: {NGC_CREATE_KEY_URL}")
    print("\n下一步:")
    print("1. 用 browser 模式跑一次")
    print("2. 观察网络请求（浏览器 DevTools）")
    print("3. 更新上面的配置")
    print("4. 运行 HTTP 模式测试")
