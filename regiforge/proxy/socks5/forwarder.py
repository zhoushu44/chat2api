"""将带认证的远端 SOCKS5 转换为本地免认证 SOCKS5。"""
from __future__ import annotations

import select
import socket
import threading

import socks


class SimpleSOCKS5Forwarder:
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

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("SOCKS5 连接提前关闭")
            data.extend(chunk)
        return bytes(data)

    def start_sync(self) -> str:
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", self.local_port))
        self.server_socket.listen(64)
        self.server_socket.settimeout(1.0)
        self.local_port = int(self.server_socket.getsockname()[1])
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return f"socks5://127.0.0.1:{self.local_port}"

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
            version, method_count = self._recv_exact(client, 2)
            if version != 5:
                raise ConnectionError("本地客户端不是 SOCKS5")
            self._recv_exact(client, method_count)
            client.sendall(b"\x05\x00")

            version, command, reserved, address_type = self._recv_exact(client, 4)
            if version != 5 or command != 1:
                client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            if address_type == 1:
                address_payload = self._recv_exact(client, 4)
            elif address_type == 3:
                length = self._recv_exact(client, 1)
                address_payload = length + self._recv_exact(client, length[0])
            elif address_type == 4:
                address_payload = self._recv_exact(client, 16)
            else:
                client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            destination_port = self._recv_exact(client, 2)

            if address_type == 1:
                destination_host = socket.inet_ntoa(address_payload)
            elif address_type == 3:
                destination_host = address_payload[1:].decode("idna")
            else:
                destination_host = socket.inet_ntop(socket.AF_INET6, address_payload)
            destination_port_number = int.from_bytes(destination_port, "big")

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
            remote.connect((destination_host, destination_port_number))
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

            client.settimeout(None)
            remote.settimeout(None)
            self._relay(client, remote)
        except (ConnectionError, OSError, PermissionError, ValueError):
            pass
        finally:
            client.close()
            if remote is not None:
                remote.close()

    def _relay(self, client: socket.socket, remote: socket.socket) -> None:
        sockets = [client, remote]
        while self.running:
            readable, _, exceptional = select.select(sockets, [], sockets, 30)
            if exceptional:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                (remote if source is client else client).sendall(data)

    def stop(self) -> None:
        self.running = False
        if self.server_socket is not None:
            self.server_socket.close()
