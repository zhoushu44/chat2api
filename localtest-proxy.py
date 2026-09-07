"""本地测试用 CONNECT 代理：绕过被污染的 DNS，硬编码上游真实 IP。仅本地测试用，不上线。"""
import socket
import threading

MAP = {
    "chatgpt.com": "104.18.32.47",
    "auth.openai.com": "104.18.41.241",
    "android.chatgpt.com": "104.18.32.47",
}

def fwd(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except Exception:
        pass
    for s in (a, b):
        try:
            s.close()
        except Exception:
            pass

def handle(c):
    try:
        req = b""
        while b"\r\n\r\n" not in req:
            d = c.recv(4096)
            if not d:
                c.close()
                return
            req += d
            if len(req) > 65536:
                c.close()
                return
        line = req.split(b"\r\n")[0].decode("latin1")
        parts = line.split(" ")
        if len(parts) < 2:
            c.close()
            return
        target = parts[1]
        if ":" in target:
            host, port = target.rsplit(":", 1)
        else:
            host, port = target, "443"
        ip = MAP.get(host.lower(), host)
        u = socket.create_connection((ip, int(port)), timeout=15)
        c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        threading.Thread(target=fwd, args=(c, u), daemon=True).start()
        fwd(u, c)
    except Exception:
        try:
            c.close()
        except Exception:
            pass

def main():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 18080))
    srv.listen(100)
    print("connect-proxy on 127.0.0.1:18080", flush=True)
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

if __name__ == "__main__":
    main()
