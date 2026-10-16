# -*- coding: utf-8 -*-
"""SSH 综合工具：读文件 / 跑命令"""
import sys, paramiko

HOST, USER, PASS = "195.72.185.32", "root", "6Qz6ao0T1zvL"

def run(cmd, timeout=120):
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, 22, USER, PASS, timeout=20)
    try:
        _, out, err = cli.exec_command(cmd, timeout=timeout)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        return o, e
    finally:
        cli.close()

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "read":
        path = sys.argv[2]
        o, e = run(f"cat '{path}'")
        sys.stdout.write(o)
        if e.strip():
            sys.stderr.write("STDERR: " + e)
    else:
        # run 模式：后面所有参数拼成一条命令
        cmd = " ".join(sys.argv[2:])
        o, e = run(cmd)
        sys.stdout.write(o)
        if e.strip():
            sys.stderr.write("STDERR: " + e)
