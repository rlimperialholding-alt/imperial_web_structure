#!/usr/bin/env python3
"""Task65 kompenzáló ellenőrzés a templates-shard html-rule kivételei mögé.

Az ``.github/workflows/imperial-adas-semgrep.yml`` platform-core
Jinja-sablon shardja két html-szabályt zár ki
(``html.security.audit.missing-integrity.missing-integrity`` és
``html.security.plaintext-http-link.plaintext-http-link``), mert a semgrep
html-parsere a Jinja-konstrukciókat (``{% %}``/``{{ }}``) nem tudja teljesen
parse-olni (87 partial parse a Task64 remote runban). A kizárás minimális
path-scope-ú (csak a ``services/platform-core/app/templates`` könyvtár,
csak az a shard; minden más HTML path a rest scanben a teljes
szabályhalmazzal fut), és ezen szkript a kizárt szabályok biztonsági
tulajdonságait determinisztikusan, fail-closed módon ellenőrzi ugyanezen a
path-körön:

- remote ``<script src="https?://...">``/``<link href="https?://...">``
  ``integrity`` attribútum nélkül → FAIL (missing-integrity tulajdonság);
- ``http://`` (nem TLS) hivatkozás ``<a href>``/``<link href>``/``<script
  src>``/``<img src>``/``<form action>`` attribútumban → FAIL
  (plaintext-http-link tulajdonság).

A kimenet csak fájlnevet, sorszámot és tulajdonságnevet közöl, titkot vagy
tartalmat nem; a lista rendezett, a report korlátos.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "services" / "platform-core" / "app" / "templates"
_MAX_VIOLATION_ROWS = 25

_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>", re.IGNORECASE | re.DOTALL)
_LINK_TAG_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE | re.DOTALL)
_ANCHOR_TAG_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE | re.DOTALL)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE | re.DOTALL)
_INTEGRITY_RE = re.compile(r"\bintegrity\s*=", re.IGNORECASE)
_ATTR_RE = re.compile(
    r"(?:src|href|action)\s*=\s*([\"'])([^\"']+)\1", re.IGNORECASE
)
_REMOTE_URL_RE = re.compile(r"^https?://", re.IGNORECASE)
_PLAINTEXT_HTTP_RE = re.compile(r"^http://", re.IGNORECASE)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _violations_for(path: Path) -> list[tuple[int, str]]:
    """(sorszám, tulajdonságnév) párok egy sablonfájlra."""
    text = path.read_text(encoding="utf-8")
    violations: list[tuple[int, str]] = []
    for pattern, attribute_kind in (
        (_SCRIPT_TAG_RE, "script"),
        (_LINK_TAG_RE, "link"),
        (_ANCHOR_TAG_RE, "anchor"),
        (_IMG_TAG_RE, "img"),
        (_FORM_TAG_RE, "form"),
    ):
        for tag_match in pattern.finditer(text):
            tag = tag_match.group(0)
            for attr_match in _ATTR_RE.finditer(tag):
                url = attr_match.group(2)
                if _PLAINTEXT_HTTP_RE.match(url):
                    violations.append(
                        (_line_number(text, tag_match.start()), "plaintext-http-link")
                    )
                elif (
                    attribute_kind in ("script", "link")
                    and _REMOTE_URL_RE.match(url)
                    and not _INTEGRITY_RE.search(tag)
                ):
                    violations.append(
                        (_line_number(text, tag_match.start()), "missing-integrity")
                    )
    return violations


def main() -> int:
    if not TEMPLATES_DIR.is_dir():
        print(
            "check_scan_exception_compensations: FAIL - templates directory is missing",
            file=sys.stderr,
        )
        return 1
    report: list[tuple[str, int, str]] = []
    for path in sorted(TEMPLATES_DIR.glob("**/*.html")):
        try:
            for line, kind in _violations_for(path):
                report.append((path.name, line, kind))
        except (OSError, UnicodeDecodeError) as exc:
            print(
                f"check_scan_exception_compensations: FAIL - {path.name}: {exc}",
                file=sys.stderr,
            )
            return 1
    if report:
        omitted = max(0, len(report) - _MAX_VIOLATION_ROWS)
        for path_name, line, kind in report[:_MAX_VIOLATION_ROWS]:
            print(
                f"check_scan_exception_compensations: FAIL - {path_name}:{line} "
                f"violates {kind}",
                file=sys.stderr,
            )
        if omitted:
            print(
                f"check_scan_exception_compensations: FAIL - {omitted} further "
                "violation(s) omitted",
                file=sys.stderr,
            )
        return 1
    count = len(list(TEMPLATES_DIR.glob("**/*.html")))
    print(
        "check_scan_exception_compensations: PASS - "
        f"{count} template file(s) satisfy the excluded html-rule properties "
        "(integrity, plaintext-http-link)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
