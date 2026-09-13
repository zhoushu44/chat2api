# proxy/wary

## 职责

Wary 粘性 WARP 代理池 Provider：固定一个 API 地址动态获取代理，URL 含 `{sid}` 时每账号生成唯一粘性会话 ID、固定独立出口，规避“身份到处飘”。

## 包含

| 文件 | 说明 |
|------|------|
| `provider.py` | 单一 API 地址抓取、代理规范化与带认证转发处理 |

## 使用方式

`api_url` 字段填写代理池 API 地址：

```text
http://192.6.121.16:4433/api/proxies?num=1&type=txt&format=n&sid=chatgpt-{sid}&time=20
```

**工作机制**：

- **粘性会话**：URL 含 `{sid}` 时每次 `acquire()` 生成唯一会话 ID 并替换，每账号固定独立出口；不写 `{sid}` 则按 API 默认轮换
- **返回格式**：取响应首行非空文本作为代理地址（纯文本或 HTML 表格首格）
- **带认证代理**：自动走本地 HTTP 转发器，失败回退 `socks5h://`
- **协议规范**：无前缀时自动补 `socks5://`

## 相关

- [代理系统](../README.md)
- [ChatGPT 注册项目](../../projects/chatgpt_register/)
