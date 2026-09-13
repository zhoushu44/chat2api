# Clash 代理 Provider

通过 Clash API 动态获取当前选中的代理节点。

## 使用场景

- 需要频繁切换代理 IP（每个账号自动切换）
- 已有 Clash 客户端在运行
- 需要利用 Clash 的代理组管理和故障切换功能

## 配置字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `clash_api_url` | 是 | Clash API 地址，如 `http://127.0.0.1:9090` |
| `clash_api_secret` | 否 | Clash API 密钥（在 Clash 配置中设置） |
| `clash_group_name` | 否 | 代理组名称，不填则使用第一个 |
| `clash_local_port` | 否 | 本地 SOCKS5 端口，默认 `7897` |

## 工作原理

1. 通过 Clash API 获取当前代理组信息
2. 读取当前选中的节点名称
3. 返回 `socks5://127.0.0.1:7897` 格式的代理地址
4. 浏览器和 API 请求通过此代理访问

## 前提条件

1. **Clash 客户端已启动**：
   - Windows: Clash for Windows / Clash Verge
   - macOS: ClashX Pro / Clash Verge
   - Linux: Clash 核心 + 配置文件

2. **开启了 API 访问**：
   ```yaml
   # Clash 配置
   external-controller: 127.0.0.1:9090
   secret: your_api_secret
   ```

3. **启用了 SOCKS5 端口**：
   ```yaml
   socks-port: 7897
   ```

## 与 SOCKS5 Provider 的区别

| 特性 | `socks5` Provider | `clash` Provider |
|------|-------------------|------------------|
| 代理来源 | 手动配置或 API 获取 | Clash 当前选中节点 |
| 切换方式 | 轮换配置中的代理列表 | 依赖 Clash 代理组切换 |
| 故障处理 | 自动标记失败代理 | 依赖 Clash 自动切换 |
| 适用场景 | 静态代理池 | 动态代理管理 |

## 示例配置

```json
{
  "proxy": {
    "clash": {
      "clash_api_url": "http://127.0.0.1:9090",
      "clash_api_secret": "your-clash-secret",
      "clash_group_name": "",
      "clash_local_port": 7897
    }
  }
}
```

## 相关

- [Clash 官方文档](https://github.com/Dreamacro/clash)
- [Clash API 参考](https://github.com/Dreamacro/clash/wiki/external-controller)
