import paramiko, os

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('195.72.185.32', username='root', password='6Qz6ao0T1zvL', timeout=30)
cmds = [
    "cd /tmp/c2a-push && git am --abort 2>/dev/null; rm -rf .git/rebase-apply",
    "cd /tmp/c2a-push && git show HEAD:internal/api/web_dist/index.html | sed 's/\\r$//' > /tmp/idx_lf.html",
    "cd /tmp/c2a-push && cp /tmp/idx_lf.html internal/api/web_dist/index.html && git add internal/api/web_dist/index.html && git commit -m 'chore: index.html line-ending normalize' --no-verify 2>&1 | tail -1",
]
for cmd in cmds:
    _,o,e = c.exec_command(cmd, timeout=120)
    print(o.read().decode()[:200])
_,o,e = c.exec_command("cd /tmp/c2a-push && git am /tmp/p17.patch 2>&1 | tail -2", timeout=180)
print('am:', o.read().decode()[:200])
_,o,e = c.exec_command("cd /tmp/c2a-push && git log --oneline -3", timeout=60)
print(o.read().decode()[:250])
token = os.environ['GH_TOKEN']
_,o,e = c.exec_command('cd /tmp/c2a-push && git push https://zhoushu44:' + token + '@github.com/zhoushu44/chat2api.git master 2>&1 | tail -2', timeout=300)
print('push:', o.read().decode()[:250])
c.close()
