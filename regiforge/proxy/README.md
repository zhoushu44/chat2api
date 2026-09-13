# proxy

## 职责

代理 Provider 层：提供 SOCKS5 代理或直连模式，供浏览器注册流程和邮箱/验证码 API 使用。

## 包含

| 子目录 / 文件 | 说明 |
|-------------|------|
| [`none/`](none/) | `none`：直连模式（不使用代理） |
| [`socks5/`](socks5/) | `socks5`：SOCKS5 多行轮换或 API 动态获取 |
| [`http_proxy/`](http_proxy/) | `http_proxy`：HTTP/HTTPS 多行轮换（适合 ChatGPT HTTP 模式） |
| [`relay_scout/`](relay_scout/) | `relay_scout`：Relay Scout SOCKS5 代理池 API（项目 + Key，可选粘性 session） |
| [`clash/`](clash/) | `clash`：Clash API 动态节点（通过 Clash 客户端获取当前代理） |
| [`mihomo/`](mihomo/) | `mihomo`：mihomo WebUI API 动态入口（模式 E 等，服务端自动切换上游） |
| [`wary/`](wary/) | `wary`：Wary 粘性 WARP 代理池 API（`{sid}` 每账号固定独立出口） |
| `base.py` | `ProxyProvider` 抽象基类 |

## 全局代理支持

**所有 HTTP 请求统一通过代理**：

1. **浏览器会话**：Chrome 启动时注入 `--proxy-server` 参数
2. **邮箱 API**：`TaskRunner` 将代理配置注入 `email_cfg["proxy"]`，TempMail / MailNest / Cloudflare Worker 的 `requests` 调用自动使用代理
3. **验证码 API**：YesCaptcha / CaptchaRun 等通过 `httpx` / `requests` 请求时自动使用代理
4. **导出 API**：Sub2API / Grok2API 导入账号池时通过代理

### 配置方式

#### 方式 1：手动配置多行代理（推荐）

在 Web 控制台「SOCKS5 链接」字段填写（支持多行）：

```
socks5://user:pass@host1:port1
socks5://user:pass@host2:port2
socks5://user:pass@host3:port3
```

**轮换与故障切换机制**：

1. **顺序轮换**：每个注册账号自动使用下一个代理
   - 账号 1 → 第 1 个代理
   - 账号 2 → 第 2 个代理
   - 账号 N → 第 N 个代理（循环）
   - 实现：`Socks5Provider._proxy_index` 递增取模

2. **失败自动标记**：当代理返回 `proxy_dead`、`proxy_reset`、`tls_error` 或异常时：
   - 自动加入失败集合 `_failed_proxies`
   - 下次轮换时跳过该代理
   - 日志显示：`[idx] 代理 socks5://... 标记为失败，自动切换到下一个`
   - 实现：`TaskRunner` 根据 `result.failure_class` 标记

3. **成功清除标记**：代理成功后从失败集合移除，恢复轮换
   - 实现：`result.apikey` 存在时 `proxy._failed_proxies.discard(current_proxy)`

4. **格式兼容**：
   - 自动清理每行首尾空格（`trim()`）
   - 过滤空行
   - 支持 `socks5://` 和 `socks5h://` 协议前缀

5. **带认证代理自动转换**（多 Provider 已覆盖）：
   - `socks5://user:pass@host:port` → 本地 HTTP 转发器 `http://127.0.0.1:xxxx`
   - 转发器创建失败时自动降级到 `socks5h://user:pass@host:port`
   - `curl_cffi` 原生支持两种格式，确保代理可用
   - 已覆盖：`socks5` / `wary` / `mihomo` / `relay_scout` / `clash`（详见 [docs/SOCKS5_AUTH_COMPAT.md](../docs/SOCKS5_AUTH_COMPAT.md)）

#### 方式 2：API 动态获取

在 Web 控制台「代理 API 地址」字段填写 API 端点：

```
https://api.proxy.com/get
```

**配置字段**（在 `data/config.json` 或 Web 控制台）：

```json
{
  "proxy": {
    "socks5": {
      "api_url": "https://api.proxy.com/get",
      "api_key": "your-api-key",
      "timeout": 10,
      "protocol": "socks5",
      "json_path": "data.proxy"
    }
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `api_url` | 是 | API 端点地址 |
| `api_key` | 否 | 认证密钥（`Bearer` 或 `X-API-Key`） |
| `timeout` | 否 | 请求超时秒数，默认 10 |
| `protocol` | 否 | `socks5` 或 `socks5h`，默认 `socks5` |
| `json_path` | 否 | JSON 提取路径，如 `data.proxy` |

**支持的返回格式**：
- **纯文本**：每行一个 `socks5://host:port` 或 `host:port`
- **JSON 对象**：自动提取 `proxy`、`ip`、`host`、`address` 等字段
- **JSON 数组**：`["host:port", ...]` 或 `[{"ip": "...", "port": ...}]`
- **HTML 表格**：`<table><tr><td>host</td><td>port</td></tr></table>`

**工作机制**：
1. HTTP GET 请求 API
2. 根据响应类型自动选择解析器
3. 从多个代理中**随机选择**一个
4. 标准化为 `socks5://` 格式

**优先级**：API 模式 > 手动配置模式 > 直连

## 如何扩展

新增代理 Provider：

1. 在 `proxy/<vendor>/` 下创建目录
2. 实现 `provider.py`，继承 `ProxyProvider` 基类
3. 实现 `acquire()` 方法返回 `ProxyInfo`
4. 更新本 README 的「包含」表格

## 相关

- [全局配置](../core/README.md)
- [浏览器会话](../core/README.md#浏览器会话)
