#!/usr/bin/env python3
"""Check every canonical route and bundled asset against a running HTTP server."""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    server: ThreadingHTTPServer | None = None
    if len(sys.argv) == 3 and sys.argv[1] == "--serve-local":
        port = int(sys.argv[2])
        site_root = Path(__file__).resolve().parents[1]
        os.chdir(site_root.parent)
        server = ThreadingHTTPServer(("127.0.0.1", port), SimpleHTTPRequestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}/everyday-homes"
    elif len(sys.argv) == 2:
        base_url = sys.argv[1].rstrip("/")
        site_root = Path(__file__).resolve().parents[1]
    else:
        raise SystemExit(
            "Usage: validate_http.py <base-url> | --serve-local <port>"
        )

    page_map = json.loads(
        (site_root / "data" / "page-map.json").read_text(encoding="utf-8")
    )

    urls = [f"{base_url}/"]
    for group in page_map["groups"]:
        for _page_id, route_value, _title in group["pages"]:
            route = route_value.strip("/")
            urls.append(f"{base_url}/{route}/" if route else f"{base_url}/")

    for asset in sorted((site_root / "assets").rglob("*")):
        if asset.is_file():
            relative_asset = asset.relative_to(site_root).as_posix()
            urls.append(f"{base_url}/{relative_asset}")

    failures: list[dict[str, str | int]] = []
    for url in urls:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Everyday-QA/1.0"})
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    failures.append({"url": url, "status": response.status})
        except Exception as exc:  # pragma: no cover - command-line diagnostic
            failures.append({"url": url, "error": str(exc)})

    print(
        json.dumps(
            {"checked": len(urls), "failed": failures},
            ensure_ascii=False,
        )
    )
    if server is not None:
        server.shutdown()
        server.server_close()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
