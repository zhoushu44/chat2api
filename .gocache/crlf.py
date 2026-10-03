import paramiko, os

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('195.72.185.32', username='root', password='6Qz6ao0T1zvL', timeout=30)
cmds = [
    "file /tmp/p17.patch | head -1",
    "sed -i 's/\\r$//' /tmp/p17.patch && file /tmp/p17.patch",
    "cd /tmp/c2a-push && git am --abort 2>/dev/null; git am /tmp/p17.patch 2>&1 | tail -2",
    "cd /tmp/c2a-push && git log --oneline -1",
]
for cmd in cmds:
    _,o,e = c.exec_command(cmd, timeout=180)
    print(o.read().decode()[:250])
token = os.environ['GH_TOKEN']
_,o,e = c.exec_command('cd /tmp/c2a-push && git push https://zhoushu44:' + token + '@github.com/zhoushu44/chat2api.git master 2>&1 | tail -2', timeout=300)
print('push:', o.read().decode()[:250])
c.close()
