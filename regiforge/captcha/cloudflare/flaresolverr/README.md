# FlareSolverr Provider

通过远程 FlareSolverr 服务解决 Cloudflare 挑战。

## 特性

- ✅ 支持远程 FlareSolverr 服务（HTTP API）
- ✅ 可选配合 mihomo 等 SOCKS5/HTTP 代理
- ✅ 返回完整的 Cookie、User-Agent 和页面内容
- ✅ 适用于所有需要过 Cloudflare 的项目
- ✅ 异步 API，易于集成

## 部署 FlareSolverr

参考教程：[FlareSolverr Docker 部署教程](../../../C:/知识库/史蒂夫周/注册机/FlareSolverr%20Docker%20部署教程.md)

快速部署：

```bash
docker run -d \
  --name flaresolverr \
  --restart always \
  -p 0.0.0.0:8191:8191 \
  -e LOG_LEVEL=info \
  -e HEADLESS=true \
  ghcr.io/flaresolverr/flaresolverr:latest
```

## 配置

### 方式一：Web 控制台配置

在 Web 控制台的 Provider 配置页面添加：

```json
{
  "captcha.cloudflare.flaresolverr": {
    "api_url": "http://192.6.121.16:8191/v1",
    "proxy": {
      "url": "socks5://mihomo:7890",
      "username": "user",
      "password": "pass"
    },
    "max_timeout": 60000
  }
}
```

### 方式二：代码配置

```python
from captcha.cloudflare.flaresolverr.provider import FlareSolverrProvider

provider = FlareSolverrProvider()
provider.configure({
    "api_url": "http://192.6.121.16:8191/v1",
    "proxy": {
        "url": "socks5://mihomo:7890",
        "username": "user",
        "password": "pass"
    },
    "max_timeout": 60000
})
```

## 使用示例

### 基础调用

```python
result = await provider.solve(
    sitekey="",  # 可选
    page_url="https://auth.openai.com/"
)

if result:
    data = json.loads(result)
    cf_clearance = data["cf_clearance"]
    user_agent = data["ua"]
    cookies = data["cookies"]
```

### 配合项目使用

```python
from core.base import RunContext
from captcha.cloudflare.flaresolverr.provider import FlareSolverrProvider

# 创建 Provider 实例
flaresolverr = FlareSolverrProvider()
flaresolverr.configure(ctx.config.get("captcha.cloudflare.flaresolverr"))

# 在项目中使用
async def solve_cloudflare_challenge(page_url: str):
    result = await flaresolverr.solve(
        sitekey="",
        page_url=page_url
    )
    
    if result:
        data = json.loads(result)
        # 设置 Cookie 和 User-Agent 到浏览器或 HTTP 会话
        return data
    else:
        raise RuntimeError("FlareSolverr 挑战失败")
```

### 动态指定服务地址

```python
# 在调用时覆盖配置
result = await provider.solve(
    sitekey="",
    page_url="https://example.com",
    api_url="http://其他服务器：8191/v1",  # 覆盖配置
    proxy={"url": "socks5://其他代理：7890"}  # 覆盖配置
)
```

## 返回结果

```json
{
  "cf_clearance": "abc123...",
  "ua": "Mozilla/5.0 ...",
  "cookies": [
    {
      "name": "cf_clearance",
      "value": "abc123...",
      "domain": ".example.com",
      "path": "/"
    }
  ],
  "response": "<html>...</html>",
  "url": "https://最终 URL",
  "status": 200
}
```

## 与 CaptchaRun 对比

| 特性 | FlareSolverr | CaptchaRun |
|------|--------------|------------|
| 部署方式 | 自建服务 | 第三方 API |
| 成本 | 免费（自建） | 按次付费 |
| 速度 | 5-15 秒 | 10-30 秒 |
| 成功率 | 高 | 高 |
| 可控性 | 完全可控 | 依赖第三方 |
| 代理支持 | 是 | 是 |

## 常见问题

### Q: 服务无法连接
A: 检查 FlareSolverr 容器是否运行：`docker ps | grep flaresolverr`

### Q: 挑战失败
A: 尝试增加 `max_timeout` 或更换代理 IP

### Q: 返回的 Cookie 无效
A: 确保后续请求使用相同的 User-Agent 和代理 IP

## 测试

### 基础测试

```bash
# 测试 FlareSolverr 服务（无代理）
curl -X POST http://192.6.121.16:8191/v1 \
  -H "Content-Type: application/json" \
  -d '{"cmd":"request.get","url":"https://www.google.com","maxTimeout":60000}'

# 测试带代理访问（SOCKS5 带认证）
curl -X POST http://192.6.121.16:8191/v1 \
  -H "Content-Type: application/json" \
  -d '{
    "cmd":"request.get",
    "url":"https://auth.openai.com/",
    "proxy":{
      "url":"socks5://user1:pass1@172.17.0.4:7890"
    }
  }'
```

### Python 测试

```python
# tests/test_flaresolverr_noproxy.py
import asyncio
from captcha.cloudflare.flaresolverr import solve_cloudflare

async def test():
    # 无代理测试
    result = await solve_cloudflare(
        "https://auth.openai.com/",
        api_url="http://192.6.121.16:8191/v1"
    )
    print(f"cf_clearance: {result['cf_clearance'][:50]}...")
    
    # 带代理测试
    result = await solve_cloudflare(
        "https://auth.openai.com/",
        api_url="http://192.6.121.16:8191/v1",
        proxy={
            "url": "socks5://user1:pass1@172.17.0.4:7890"
        }
    )
    print(f"User-Agent: {result['ua']}")

asyncio.run(test())
```

### 测试结果

✅ **2026-08-03 测试通过**

| 测试项目 | 结果 | 说明 |
|---------|------|------|
| FlareSolverr 无代理 | ✅ 通过 | Google、ChatGPT 均可访问 |
| FlareSolverr + mihomo | ✅ 通过 | SOCKS5 认证成功，Cloudflare 挑战通过 |
| Cookie 获取 | ✅ 正常 | cf_clearance、OpenAI Cookie 等 |
| User-Agent | ✅ 正常 | Chrome 148 Linux |
| 页面内容 | ✅ 完整 | HTML 正常返回 |
