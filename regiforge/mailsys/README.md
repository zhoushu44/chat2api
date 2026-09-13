# mailsys

## 职责

邮箱 Provider 层：提供临时邮箱 / 永久邮箱后端，接收注册验证码。

## 包含

| 子目录 / 文件 | 说明 |
|-------------|------|
| [`cloudflare_worker/`](cloudflare_worker/) | `cloudflare_worker`：Cloudflare Worker 邮箱后端（CloudMail API，兼容旧 Worker/KV 字段） |
| [`mailnest/`](mailnest/) | `mailnest`：MailNest 临时邮箱 |
| [`tempmail/`](tempmail/) | `tempmail`：TempMail.lol 临时邮箱 |
| [`xunmail/`](xunmail/) | `xunmail`：寻邮 Outlook 四段式邮箱后端 |
| `base.py` | 重新导出 `EmailProvider` 基类 |
| `__init__.py` | 包标识 |

## 全局代理支持

所有邮箱 Provider 的 HTTP 请求默认通过任务代理：

- **TempMail.lol**：通过 SOCKS5 代理避免暴露中国 IP（解决 403 地区限制）
- **MailNest**：国内直连服务，**默认直连**（`TaskRunner` 不注入任务代理）；如需经代理，在 `email.mailnest.proxy` 单独指定
- **Cloudflare Worker**：通过代理访问 Worker API
- **Xunmail**：通过代理访问 Outlook Graph API

### 带认证代理自动转换（2026-07-27 修复）

邮箱 Provider 支持自动转换带认证的 SOCKS5 代理：

- **输入**：`socks5://username:password@host:port`
- **优先**：本地 HTTP 转发器 `http://127.0.0.1:xxxx`（`requests` 兼容性最好）
- **降级**：`socks5h://username:password@host:port`（转发器失败时自动回退）
- **实现**：cloudflare_worker / mailnest / tempmail Provider 的 `_convert_socks5_proxy()` 方法复用 `Socks5HttpForwarder`

配置方式：在 Web 控制台选择 `SOCKS5 代理`，`TaskRunner` 启动时自动将代理地址注入邮箱 Provider。

## 如何扩展

新增邮箱后端：

1. 在 `mailsys/<backend>/` 下创建目录
2. 实现 `provider.py`，继承 `EmailProvider` 基类
3. 实现 `generate_address()` 和 `wait_code()` 方法
4. 更新本 README 的「包含」表格

## 相关

- [代理系统](../proxy/README.md)
- [全局配置](../core/README.md)
