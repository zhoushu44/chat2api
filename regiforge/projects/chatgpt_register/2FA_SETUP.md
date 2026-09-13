# ChatGPT 2FA 设置功能

## 功能说明

新增 2FA（双重验证）设置步骤，用于:
- 自动启用 TOTP 身份验证器
- 提取并保存 TOTP secret（用于后续保活重登）
- 保存备用码（紧急恢复用）
- 提升账号保活率，解决"掉登录态"问题

## 使用方法

### Web 控制台

1. 打开 `/projects/chatgpt_register`
2. 选择 `register_mode=browser`（仅 browser 模式支持 2FA）
3. 勾选 **"启用 2FA（双重验证）"**
4. 可选：调整 `2fa_timeout`（默认 120 秒）
5. 点击「启动任务」

### 配置说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_2fa` | checkbox | false | 是否启用 2FA 设置 |
| `2fa_timeout` | number | 120 | 2FA 设置超时时间（秒） |

**注意**: 2FA 设置仅在 `register_mode=browser` 时生效，HTTP 模式不支持。

## 输出格式

### 控制台输出

```
✅ 2FA 已配置并保存
  TOTP: JBSW**** (共 16 位)
  备用码：10 个
```

### 账号产出

```json
{
  "email": "user@tempmail.com",
  "apikey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "extra": {
    "mode": "browser",
    "name": "John Doe",
    "2fa_enabled": true,
    "totp_secret": "JBSWY3DPEHPK3PXP",
    "backup_codes": ["ABCD1234", "EFGH5678", ...],
    "plan_type": "free",
    "type": "free",
    "source_type": "web"
  }
}
```

## 2FA 用途

### 1. 账号保活重登

当 accessToken 失效时，可使用保存的 TOTP secret 重新登录获取新 token:

```python
# 伪代码示例
import pyotp

totp = pyotp.TOTP(totp_secret)
code = totp.now()  # 当前 2FA 码

# 重登流程
await login(email, password)
await submit_2fa_code(code)
new_token = await get_session()
```

### 2. 紧急恢复

如账号被锁定或无法访问，使用备用码恢复:
- 每个备用码只能使用一次
- 建议保存所有 10 个备用码到安全位置

## 注意事项

1. **TOTP secret 安全**
   - 妥善保存 `totp_secret`，泄露可能导致账号被盗
   - 建议加密存储或存入密码管理器

2. **备用码使用**
   - 备用码是账号恢复的最后手段
   - 用完后建议重新生成新的备用码

3. **人工介入**
   - 当前实现需要人工输入 TOTP 码完成验证
   - 未来可集成自动 TOTP 生成（需 pyotp 库）

4. **兼容性**
   - 仅 browser 模式支持 2FA 设置
   - HTTP 模式因无浏览器会话，暂不支持

## 测试

运行测试脚本:
```bash
python tests\_live_chatgpt_2fa_test.py
```

测试结果保存在: `data/debug/chatgpt_2fa_test_result.json`

## 与 Roxy 流程对比

| 功能 | Roxy | 当前实现 |
|------|------|----------|
| 2FA 设置 | ✅ | ✅ |
| TOTP secret 提取 | ✅ | ✅ |
| 备用码保存 | ✅ | ✅ |
| 自动重登保活 | ✅ | ❌ (待实现) |
| 指纹浏览器 | ✅ (Roxy Profile) | ❌ (需配置) |

## 后续优化

1. **自动重登保活模块**
   - 定期检测 token 有效性
   - 失效时自动使用 TOTP 重登

2. **TOTP 自动生成**
   - 集成 `pyotp` 库
   - 全自动完成 2FA 验证

3. **指纹浏览器支持**
   - 支持 Roxy/AdsPower/HubStudio
   - 降低账号关联风险
