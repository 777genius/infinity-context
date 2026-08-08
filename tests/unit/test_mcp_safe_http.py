"""Credential-bearing MCP HTTP adapters must never follow redirects."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from infinity_context_mcp.safe_http import open_without_redirects


def test_credential_bearing_request_does_not_follow_redirect() -> None:
    received_authorization: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            received_authorization.append(self.headers.get("Authorization"))
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/destination")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/start",
            headers={"Authorization": "Bearer secret"},
        )
        with pytest.raises(HTTPError) as error:
            open_without_redirects(request, timeout=1)
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()

    assert error.value.code == 302
    assert received_authorization == ["Bearer secret"]
