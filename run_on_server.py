"""把本地 Python 脚本上传到服务器容器内执行（凭据外置版）。

用法: python run_on_server.py <local_script.py> [timeout_sec] [container]
凭据从 .secrets.env 读取（HOST/USER/PWD），该文件已 gitignore。
"""
import sys, os, time, paramiko

from ssh_run import get_creds

def connect(tries=8):
    host, user, pwd = get_creds()
    if not all([host, user, pwd]):
        raise SystemExit("缺少 SSH 凭据：请在 .secrets.env 配置 HOST/USER/PWD")
    auth = {}
    auth["hostname"] = host
    auth["port"] = 22
    auth["username"] = user
    auth["password"] = pwd
    auth.update(timeout=30, banner_timeout=40, auth_timeout=40, channel_timeout=40)
    last=None
    for i in range(tries):
        try:
            c=paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(**auth)
            t=c.get_transport()
            if t: t.set_keepalive(15)
            return c
        except Exception as e:
            last=e; time.sleep(4)
    raise SystemExit("ssh failed: %s"%last)

def run(cmd, timeout=1800):
    for attempt in range(4):
        try:
            c=connect()
            stdin,stdout,stderr=c.exec_command(cmd, timeout=timeout)
            while True:
                line=stdout.readline()
                if not line and stdout.channel.exit_status_ready():
                    break
                if line:
                    sys.stdout.write(line); sys.stdout.flush()
            rest=stdout.read().decode("utf-8","replace")
            if rest: sys.stdout.write(rest)
            code=stdout.channel.recv_exit_status()
            c.close()
            return code
        except Exception as e:
            sys.stdout.write("\n[conn error attempt %d: %s]\n"%(attempt+1, e)); sys.stdout.flush()
            time.sleep(5)
    return -1

def upload(local, remote):
    for attempt in range(4):
        try:
            c=connect()
            sftp=c.open_sftp()
            sftp.put(local, remote)
            sftp.close(); c.close()
            return True
        except Exception as e:
            sys.stdout.write("[sftp retry %d: %s]\n"%(attempt+1,e)); sys.stdout.flush()
            time.sleep(5)
    return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python run_on_server.py <local_script.py> [timeout_sec] [container]")
        raise SystemExit(2)
    local = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    container = sys.argv[3] if len(sys.argv) > 3 else "aiimg1"
    name = os.path.basename(local)

    if not upload(local, "/tmp/"+name):
        raise SystemExit("upload failed")
    run("docker cp /tmp/%s %s:/tmp/%s"%(name,container,name), timeout=120)
    code = run("docker exec %s python3 /tmp/%s 2>&1"%(container,name), timeout=timeout)
    run("docker exec %s rm -f /tmp/%s; rm -f /tmp/%s"%(container,name,name), timeout=60)
    print("\n[exit %d]"%code)
