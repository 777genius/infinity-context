"""Tiny TCP gateway from loopback-published ports into the shared network namespace."""

from __future__ import annotations

import selectors
import socket
import threading


class TcpGateway:
    def __init__(self, *, listen_port: int, target_port: int) -> None:
        self._listen_port = listen_port
        self._target_port = target_port

    def serve(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", self._listen_port))
        listener.listen(64)
        while True:
            client, _ = listener.accept()
            threading.Thread(target=self._bridge, args=(client,), daemon=True).start()

    def _bridge(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(("127.0.0.1", self._target_port), timeout=5)
        except OSError:
            client.close()
            return
        selector = selectors.DefaultSelector()
        try:
            client.settimeout(None)
            upstream.settimeout(None)
            selector.register(client, selectors.EVENT_READ, upstream)
            selector.register(upstream, selectors.EVENT_READ, client)
            while selector.get_map():
                for key, _ in selector.select(timeout=30):
                    source = key.fileobj
                    target = key.data
                    try:
                        data = source.recv(65536)
                    except OSError:
                        data = b""
                    if not data:
                        return
                    target.sendall(data)
        finally:
            selector.close()
            client.close()
            upstream.close()


def main() -> None:
    gateways = (
        TcpGateway(listen_port=29091, target_port=19091),
        TcpGateway(listen_port=26334, target_port=6334),
    )
    for gateway in gateways:
        threading.Thread(target=gateway.serve, daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
