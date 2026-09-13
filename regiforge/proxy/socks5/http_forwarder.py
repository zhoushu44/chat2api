"""将带认证的远端 SOCKS5 转换为本地 HTTP CONNECT 代理。"""
from __future__ import annotations

import select
import socket
import threading

import socks


class Socks5HttpForwarder:
    def __init__(
        self,
        remote_host: str,
        remote_port: int,
        username: str = "",
        password: str = "",
        local_port: int = 0,
    ) -> None:
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.username = username
        self.password = password
        self.local_port = local_port
        self.server_socket: socket.socket | None = None
        self.running = False

    def start_sync(self) -> str:
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", self.local_port))
        self.server_socket.listen(64)
        self.server_socket.settimeout(1.0)
        self.local_port = int(self.server_socket.getsockname()[1])
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return f"http://127.0.0.1:{self.local_port}"

    def _accept_loop(self) -> None:
        assert self.server_socket is not None
        while self.running:
            try:
                client, _ = self.server_socket.accept()
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, client: socket.socket) -> None:
        remote: socket.socket | None = None
        try:
            client.settimeout(15)
            request = bytearray()
            while b"\r\n\r\n" not in request and len(request) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    return
                request.extend(chunk)
            first_line = bytes(request).split(b"\r\n", 1)[0].decode("latin1")
            method, target, _ = first_line.split(" ", 2)
            if method.upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
                return
            host, port = target.rsplit(":", 1)
            blocked_hosts = {
                "accounts.google.com",
                "safebrowsingohttpgateway.googleapis.com",
                "www.google.com",
            }
            if host.strip("[]").lower() in blocked_hosts:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                return
            # SOCKS5 上游偶发 Connection reset/timeout（多账号并发或 IP 风控），
            # 重试 3 次，每次新 socket，避免单次抖动导致 502 让浏览器落到 chrome-error。
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    remote = socks.socksocket()
                    remote.set_proxy(
                        socks.SOCKS5,
                        self.remote_host,
                        self.remote_port,
                        rdns=True,
                        username=self.username,
                        password=self.password,
                    )
                    remote.settimeout(15)
                    remote.connect((host.strip("[]"), int(port)))
                    last_err = None
                    break
                except (ConnectionError, OSError, PermissionError, ValueError) as e:
                    last_err = e
                    if remote is not None:
                        try:
                            remote.close()
                        except OSError:
                            pass
                        remote = None
                    if attempt < 2:
                        import time as _t
                        _t.sleep(1.0)
            if last_err is not None:
                raise last_err
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.settimeout(None)
            remote.settimeout(None)
            self._relay(client, remote)
        except (ConnectionError, OSError, PermissionError, ValueError):
            try:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
        finally:
            client.close()
            if remote is not None:
                remote.close()

    def _relay(self, client: socket.socket, remote: socket.socket) -> None:
        sockets = [client, remote]
        while self.running:
            try:
                readable, _, exceptional = select.select(sockets, [], sockets, 30)
            except (OSError, ValueError):
                # Windows 下 socket 关闭后 select 可能抛 [Errno 9] Bad file descriptor
                return
            if exceptional:
                return
            for source in readable:
                try:
                    data = source.recv(65536)
                except (OSError, ConnectionError):
                    return
                if not data:
                    return
                try:
                    (remote if source is client else client).sendall(data)
                except (OSError, ConnectionError):
                    return

    def stop(self) -> None:
        self.running = False
        if self.server_socket is not None:
            self.server_socket.close()
