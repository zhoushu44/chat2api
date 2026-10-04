import os, sys, hashlib, subprocess
sys.path.insert(0, r"C:\Users\zs\Desktop\chat2api")
from ssh_run import connect

LOCAL = r"C:\Users\zs\Desktop\chat2api"
FILES = [
    "internal/superres/plan.go",
    "internal/superres/client.go",
    "internal/superres/enhance.go",
    "internal/superres/wire.go",
    "internal/superres/plan_test.go",
    "internal/config/config.go",
]

def md5(b): return hashlib.md5(b).hexdigest()

# 1. 清理残留脚本
leftover = os.path.join(LOCAL, "sync_webdist_stage.py")
if os.path.exists(leftover):
    os.remove(leftover)
    print("已删除残留脚本 sync_webdist_stage.py")

# 2. 比对：本地 HEAD(git 已提交) vs 服务器已验证源码
print("\n=== 本地 HEAD 内容 vs 服务器 /tmp/c2a-push（已通过实测）===")
c = connect(); sftp = c.open_sftp()
all_match = True
for f in FILES:
    # 本地 HEAD 内容
    r = subprocess.run(["git", "show", "HEAD:" + f], cwd=LOCAL,
                       capture_output=True)
    local_data = r.stdout
    # 服务器内容
    with sftp.open("/tmp/c2a-push/" + f) as fh:
        remote_data = fh.read()
    ok = md5(local_data) == md5(remote_data)
    all_match &= ok
    print("  %-38s %s  (local=%d remote=%d)" % (
        f, "一致" if ok else "不一致", len(local_data), len(remote_data)))
sftp.close(); c.close()

print("\nVERDICT:", "HEAD_SAME_AS_TESTED" if all_match else "MISMATCH_NEEDS_FIX")
