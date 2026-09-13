from .provider import FlareSolverrProvider, PROVIDER
from .utils import solve_cloudflare, solve, configure, get_provider, apply_to_session

# FlareSolverr Provider - 通过远程 FlareSolverr 服务解决 Cloudflare 挑战
# 文档：https://github.com/FlareSolverr/FlareSolverr
#
# 快速使用：
#   from captcha.cloudflare.flaresolverr import solve_cloudflare
#
#   result = await solve_cloudflare(
#       "https://auth.openai.com/",
#       proxy={"url": "socks5://mihomo:7890"}
#   )
#
#   if result:
#       print(f"cf_clearance: {result['cf_clearance']}")
#
# 配置示例（在 Web 控制台或 data/config.json）：
# {
#   "captcha.cloudflare.flaresolverr": {
#     "api_url": "http://192.6.121.16:8191/v1",
#     "proxy": {
#       "url": "socks5://mihomo:7890",
#       "username": "user",
#       "password": "pass"
#     },
#     "max_timeout": 60000
#   }
# }

PROVIDER = "FlareSolverrProvider"
