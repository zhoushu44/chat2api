import paramiko, os, base64, time

def connect():
    cl = paramiko.SSHClient(); cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cl.connect('195.72.185.32', username='root', password='6Qz6ao0T1zvL', timeout=30)
    return cl

c = connect()
data = open(os.environ['BUNDLE_GZ'], 'rb').read()
b64 = base64.b64encode(data).decode()
print('bundle gz b64 len:', len(b64))
c.exec_command("rm -f /tmp/c17.b64 /tmp/c17.bundle.gz /tmp/c17.bundle", timeout=30)[1].channel.recv_exit_status()
CH = 50000
i = 0; retries = 0
while i < len(b64):
    try:
        _,o,e = c.exec_command("printf '%s' '" + b64[i:i+CH] + "' >> /tmp/c17.b64 && echo OK", timeout=60)
        if 'OK' not in o.read().decode(): raise RuntimeError('noack')
        i += CH; retries = 0
    except Exception as ex:
        retries += 1
        if retries > 5: raise
        print('reconnect at', i, str(ex)[:50])
        time.sleep(3)
        try: c.close()
        except: pass
        c = connect()
print('bundle upload done')
cmds = [
    "base64 -d /tmp/c17.b64 > /tmp/c17.bundle.gz && gunzip -f /tmp/c17.bundle.gz && wc -c /tmp/c17.bundle",
    "cd /tmp/c2a-push && git am --abort 2>/dev/null; git fetch /tmp/c17.bundle HEAD 2>&1 | tail -1 && git log --oneline FETCH_HEAD -1",
    "cd /tmp/c2a-push && git merge --ff-only FETCH_HEAD 2>&1 | tail -1 && git log --oneline -1",
]
for cmd in cmds:
    _,o,e = c.exec_command(cmd, timeout=120)
    print(o.read().decode()[:200])
token = os.environ['GH_TOKEN']
_,o,e = c.exec_command('cd /tmp/c2a-push && git push https://zhoushu44:' + token + '@github.com/zhoushu44/chat2api.git master 2>&1 | tail -2', timeout=300)
print('push:', o.read().decode()[:250])
c.close()
