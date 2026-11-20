#!/usr/bin/env python3
"""Run the deployed website locally, with no AWS deployment.

Serves aws/website/ and ../sample_data/ and runs the real Lambda handler behind
/api, calling Amazon Comprehend with your local AWS credentials.

    source ~/AdvDevGenAI/.venv/bin/activate
    python aws/scripts/dev_server.py            # then open http://127.0.0.1:8000

Binds to 127.0.0.1 only. API Gateway throttling and the IP allow-list are not simulated.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

AWS_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = AWS_DIR.parent
sys.path[:0] = [str(AWS_DIR / "lambda_functions"), str(DEMO_DIR)]
os.environ.setdefault("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

import api_handler  # noqa: E402  (needs the sys.path entries above)

SITE_DIR = AWS_DIR / "website"
SAMPLE_DIR = DEMO_DIR / "sample_data"
HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", "8000"))
CONFIG_JS = b"window.COMPREHEND_API_URL = '/api';\n"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else None
        route = urlparse(self.path).path[len("/api"):] or "/"
        result = api_handler.lambda_handler({"httpMethod": method, "resource": route, "body": body}, None)
        self._send(result["statusCode"], result["body"].encode("utf-8"), "application/json")

    def _static(self, base: Path, relative: str) -> None:
        target = (base / relative).resolve()
        if base.resolve() not in target.parents or not target.is_file():
            self._send(404, b"Not found", "text/plain")
            return
        types = {".html": "text/html", ".js": "application/javascript", ".css": "text/css",
                 ".csv": "text/csv", ".txt": "text/plain", ".svg": "image/svg+xml"}
        self._send(200, target.read_bytes(), types.get(target.suffix, "application/octet-stream") + "; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self._api("GET")
        elif path == "/config.js":
            self._send(200, CONFIG_JS, "application/javascript")
        elif path.startswith("/sample_data/"):
            self._static(SAMPLE_DIR, path[len("/sample_data/"):])
        else:
            self._static(SITE_DIR, path.lstrip("/") or "index.html")

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path.startswith("/api/"):
            self._api("POST")
        else:
            self._send(404, b"Not found", "text/plain")

    def log_message(self, fmt, *args):  # request lines only, never bodies (they contain PII)
        sys.stderr.write("%s %s\n" % (self.command, self.path))


if __name__ == "__main__":
    print(f"Comprehend demo running at http://{HOST}:{PORT}  (region {os.environ['AWS_REGION']}, Ctrl+C to stop)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
