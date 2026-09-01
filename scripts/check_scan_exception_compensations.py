#!/usr/bin/env python3
"""Task65/Task66 kompenzáló ellenőrzés a templates-shard html-rule kivételei mögé.

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
path-körön.

Task66 review-remediáció (Review-2 MEDIUM): a korábbi, csak idézőjeles
attribútumokat ismerő regex-közelítés helyett valódi HTML-tokenizer
(``html.parser.HTMLParser``, ``convert_charrefs=True``) vizsgálja a
``script``/``link``/``a``/``img``/``form`` elemek ``src``/``href``/
``action`` attribútumait. Így a következő esetek is fail-closed módon
ellenőrzöttek:

- idézőjeles ÉS idézőjel nélküli attribútumértékek (``src=http://…``);
- HTML-entity-dekódolt értékek (``http&#58;//…`` a dekódolás után vizsgált);
- Jinja/dinamikus, URL-t hordozó értékek (``src="{{ 'http://' + host }}"``,
  ``href="https://{{ cdn_host }}/…"``, idézőjelben ``>`` jelet tartalmazó
  Jinja-kifejezések is — a tokenizer a valós taghatárokat követi);
- protocol-relative ``//host/…`` remote hivatkozások (script/link integrity
  tulajdonság szempontjából remote-nak minősülnek).

A tulajdonság-ellenőrzés:

- plaintext-http-link: a ``src``/``href``/``action`` érték ``http``
  szóhatáros szószeletet ÉS ``://`` URL-tokent tartalmaz (lefedi a
  ``http://`` literált, a kisbetű/nagybetű változatokat, a
  ``{{'http'}}://`` és entity-dekódolt obfuszkációt; a ``https://`` szó
  nem illeszkedik a ``\bhttp\b`` mintára) → FAIL;
- missing-integrity: ``script``/``link`` elem ``src``/``href`` értéke
  remote (``://`` tokent tartalmaz, vagy ``//`` prefixszel indul) és a tag
  ``integrity`` attribútuma hiányzik → FAIL.

A kimenet csak fájlnevet, sorszámot és tulajdonságnevet közöl, titkot vagy
tartalmat nem; a lista rendezett, a report korlátos.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "services" / "platform-core" / "app" / "templates"
_MAX_VIOLATION_ROWS = 25

_URL_ATTRIBUTES = ("src", "href", "action")
_MISSING_INTEGRITY_TAGS = ("script", "link")
_CHECKED_TAGS = _MISSING_INTEGRITY_TAGS + ("a", "img", "form")
# A ``http`` szóhatáros szószelet (a ``https`` nem illeszkedik) és a ``://``
# URL-token együttes jelenléte azonosítja a plaintext-http hivatkozást,
# idézőjelektől, Jinja-konstrukcióktól és entity-dekódolástól függetlenül.
_HTTP_WORD_RE = re.compile(r"\bhttp\b", re.IGNORECASE)
_SCHEME_TOKEN = "://"


class _TemplateURLCheckParser(HTMLParser):
    """Valódi HTML-tokenizer a URL-t hordozó attribútumok fail-closed
    ellenőrzésére; a Jinja-blokkokat adatként kezeli, az attribútumértékeket
    entity-dekódoltan adja vissza (``convert_charrefs=True``)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.violations: set[tuple[int, str]] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag, attrs)

    def _check_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _CHECKED_TAGS:
            return
        line, _ = self.getpos()
        attr_map = {name.lower(): value or "" for name, value in attrs}
        has_integrity = "integrity" in attr_map
        for name in _URL_ATTRIBUTES:
            if name not in attr_map:
                continue
            value = attr_map[name].strip()
            if not value:
                continue
            if _HTTP_WORD_RE.search(value) and _SCHEME_TOKEN in value:
                self.violations.add((line, "plaintext-http-link"))
            if (
                tag in _MISSING_INTEGRITY_TAGS
                and (_SCHEME_TOKEN in value or value.startswith("//"))
                and not has_integrity
            ):
                self.violations.add((line, "missing-integrity"))


def _violations_for(path: Path) -> list[tuple[int, str]]:
    """(sorszám, tulajdonságnév) párok egy sablonfájlra."""
    text = path.read_text(encoding="utf-8")
    parser = _TemplateURLCheckParser()
    parser.feed(text)
    parser.close()
    return sorted(parser.violations)


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
