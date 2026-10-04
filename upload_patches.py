"""SSH 运维工具集（凭据外置版）：执行命令 / 上传文件。

凭据从同目录 .secrets.env 读取（HOST/USER/PWD），该文件已 gitignore。
"""
import sys, time, paramiko, os

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
            c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(**auth)
            t=c.get_transport()
            if t: t.set_keepalive(15)
            return c
        except Exception as e:
            last=e; time.sleep(4)
    raise SystemExit("ssh failed: %s"%last)

def sh(cmd, timeout=900, show=True):
    for attempt in range(4):
        try:
            c=connect()
            stdin,stdout,stderr=c.exec_command(cmd, timeout=timeout)
            buf=[]
            while True:
                line=stdout.readline()
                if not line and stdout.channel.exit_status_ready(): break
                if line:
                    if show: sys.stdout.write(line); sys.stdout.flush()
                    buf.append(line)
            rest=stdout.read().decode("utf-8","replace")
            if rest and show: sys.stdout.write(rest)
            code=stdout.channel.recv_exit_status()
            err=stderr.read().decode("utf-8","replace")
            c.close()
            return code, "".join(buf)+rest, err
        except Exception as e:
            sys.stdout.write("\n[conn retry %d: %s]\n"%(attempt+1,e)); sys.stdout.flush()
            time.sleep(5)
    return -1, "", "ssh failed"

def put(local, remote):
    for attempt in range(5):
        try:
            c=connect(); sftp=c.open_sftp(); sftp.put(local, remote); sftp.close(); c.close()
            return True
        except Exception as e:
            sys.stdout.write("[sftp retry %d: %s]\n"%(attempt+1,e)); sys.stdout.flush(); time.sleep(5)
    return False

if __name__ == "__main__":
    files=["plan.go","client.go","enhance.go","wire.go"]
    ok=True
    for f in files:
        dst="/tmp/patch_"+f
        if put(os.path.join(os.path.dirname(__file__),"patched",f), dst):
            print("uploaded patch_%s"%f)
        else:
            print("FAILED patch_%s"%f); ok=False
    ap=os.path.join(os.path.dirname(__file__),"apply_patch.py")
    if put(ap, "/tmp/apply_patch.py"):
        print("uploaded apply_patch.py")
    else:
        print("FAILED apply_patch.py"); ok=False
    print("ALL_UPLOADED" if ok else "UPLOAD_ERRORS")
