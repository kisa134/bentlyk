"""Health check / landing endpoint."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"bentlyk is alive. dashboard: /api/dashboard?key=... | "
            b"telegram webhook: /api/telegram | setup: /api/setup"
        )
