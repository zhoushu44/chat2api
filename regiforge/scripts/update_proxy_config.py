"""更新配置文件中的 HTTP 代理为指定代理文件内容。

用法：
    python scripts/update_proxy_config.py <proxies_file>
"""
import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("用法：python scripts/update_proxy_config.py <proxies_file>")
    sys.exit(1)

# 读取代理文件
proxies_file = Path(sys.argv[1])
if not proxies_file.exists():
    print(f"错误：文件不存在：{proxies_file}")
    sys.exit(1)

new_proxies = [line.strip() for line in proxies_file.read_text(encoding="utf-8").splitlines() if line.strip()]
print(f"读取到代理：{len(new_proxies)} 条")

# 读取配置文件
config_file = Path("data/config.json")
config = json.load(open(config_file, 'r', encoding='utf-8'))

# 更新代理配置
config['proxy']['http_proxy']['server'] = '\n'.join(new_proxies)

# 保存配置
config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"配置文件已更新：{config_file}")
print(f"前 5 个代理:")
for i, p in enumerate(new_proxies[:5], 1):
    print(f"  {i}. {p}")
