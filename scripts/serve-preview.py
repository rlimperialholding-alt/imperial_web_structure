#!/usr/bin/env python3
"""Small local server that mirrors the Nginx website-preview routes."""

from __future__ import annotations

import argparse
import gzip
import mimetypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "sites"


class PreviewHandler(SimpleHTTPRequestHandler):
    server_version = "ImperialPreview/1.0"
    compressible_suffixes = {".css", ".html", ".js", ".json", ".svg"}

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        super().end_headers()

    def translate_path(self, raw_path: str) -> str:
        path = unquote(urlparse(raw_path).path)
        host = self.headers.get("Host", "").split(":", 1)[0].lower()

        if path == "/healthz":
            return str(ROOT / ".healthz")
        if path.startswith("/site-preview/"):
            parts = path.split("/", 3)
            if len(parts) >= 3 and parts[2]:
                brand = parts[2]
                relative = parts[3] if len(parts) == 4 else ""
                return self.safe_file(SITES / brand, relative)
        if path.startswith("/assets/"):
            return self.safe_file(SITES / "_shared" / "assets", path[8:])
        if path.startswith("/data/"):
            return self.safe_file(SITES / "_portal" / "data", path[6:])
        if host.endswith(".localhost") and host != "localhost":
            brand = host[: -len(".localhost")]
            return self.safe_file(SITES / brand, path.lstrip("/"))
        return self.safe_file(SITES / "_portal", path.lstrip("/"))

    @staticmethod
    def safe_file(root: Path, relative: str) -> str:
        root = root.resolve()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return str(ROOT / ".not-found")
        if candidate.is_dir() or not relative:
            candidate /= "index.html"
        return str(candidate)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/healthz":
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        requested_file = Path(self.translate_path(self.path))
        if requested_file.is_file():
            body = requested_file.read_bytes()
            use_gzip = (
                "gzip" in self.headers.get("Accept-Encoding", "")
                and requested_file.suffix.lower() in self.compressible_suffixes
            )
            if use_gzip:
                body = gzip.compress(body, compresslevel=6)
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(requested_file)))
            if use_gzip:
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            # Small writes avoid intermittent Winsock resets seen when the
            # standard handler sends larger local font/CSS files in one call.
            for offset in range(0, len(body), 16 * 1024):
                self.wfile.write(body[offset : offset + 16 * 1024])
                self.wfile.flush()
            return
        super().do_GET()

    def guess_type(self, path: str) -> str:
        content_type, _ = mimetypes.guess_type(path)
        if path.endswith(".woff2"):
            return "font/woff2"
        if path.endswith(".woff"):
            return "font/woff"
        return content_type or "application/octet-stream"

    def log_message(self, format: str, *args: object) -> None:
        return


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = PreviewServer((args.host, args.port), PreviewHandler)
    print(f"Serving Imperial previews at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
