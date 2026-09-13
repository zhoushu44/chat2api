import re
html = open('data/debug/nvidia_build/nvgs_register_page.html', 'r', encoding='utf-8').read()
# 找 script src
scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)', html)
print("=== Script tags ===")
for s in scripts[:20]:
    print(s[:150])

# 找 fetch/api 调用
print("\n=== API patterns in HTML ===")
patterns = re.findall(r'["\'](/api/[^"\']+)["\']', html)
for p in set(patterns):
    print(p)

# 找 create/register/signup
print("\n=== create/register patterns ===")
creates = re.findall(r'["\']([^"\']*(?:create|register|signup)[^"\']*)["\']', html, re.IGNORECASE)
for c in set(creates):
    if len(c) > 5 and len(c) < 100:
        print(c)
