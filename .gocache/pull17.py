import paramiko

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('195.72.185.32', username='root', password='6Qz6ao0T1zvL', timeout=30)
_,o,e = c.exec_command("docker pull zhoushu1/chat2api:17.0 2>&1 | tail -2", timeout=400)
print(o.read().decode()[:200])
_,o,e = c.exec_command("docker pull zhoushu1/chat2api:latest 2>&1 | tail -1 && docker images --digests zhoushu1/chat2api --format '{{.Tag}} {{.Digest}}' | head -3", timeout=400)
print(o.read().decode()[:250])
c.close()
