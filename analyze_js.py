import sys, os, re
from collections import Counter
sys.path.insert(0, r"C:\Users\zs\Desktop\chat2api")
from ssh_run import connect

c = connect()
sftp = c.open_sftp()
sftp.get("/tmp/idx_180.js", r"C:\Users\zs\Desktop\chat2api\idx_180.js")
sftp.close(); c.close()
print("downloaded:", os.path.getsize(r"C:\Users\zs\Desktop\chat2api\idx_180.js"), "bytes")

data = open(r"C:\Users\zs\Desktop\chat2api\idx_180.js", encoding="utf-8", errors="replace").read()

print("\n=== 'super' 出现位置上下文 ===")
for m in re.finditer(r'super', data):
    s = max(0, m.start()-100); e = min(len(data), m.end()+100)
    print("  ...", data[s:e].replace("\n"," ")[:200])
    print()

print("=== 中文字符串（设置相关过滤）===")
zh = re.findall(r'[\u4e00-\u9fff][\u4e00-\u9fff\w：:（()）、]{1,20}', data)
c2 = Counter(zh)
hits = [s for s, n in c2.most_common(300) if any(k in s for k in '超清缩放存桶压设密钥画质倍率分辨无损锐腾讯')]
for s in hits[:30]:
    print(f"  {c2[s]:3d}x  {s}")
if not hits:
    print("  (无设置相关中文，打印全部高频中文)")
    for s, n in c2.most_common(40):
        print(f"  {n:3d}x  {s}")

print("\n=== 表单字段名扫描（settings 相关的 v-model / name）===")
for kw in ["secret_id","bucket","region","output_format","output_quality","upload_endpoint","enabled",
           "super_resolution","SuperRes","超分","disable_exact"]:
    n = data.count(kw)
    print(f"  {kw}: {n}")
