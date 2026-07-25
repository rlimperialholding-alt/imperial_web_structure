#!/usr/bin/env python3
"""Audit every registered website preview and all recursively referenced assets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen


CSS_URL_RE = re.compile(r"url\(\s*([\"']?)(.*?)\1\s*\)", re.IGNORECASE)
CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?[\"']([^\"']+)[\"']\s*\)?", re.IGNORECASE
)
JS_IMPORT_RE = re.compile(
    r"""(?:import\s*\(\s*|(?:import|export)\s+(?:[\s\S]*?\s+from\s+)?)
        ["']([^"']+)["']""",
    re.VERBOSE,
)
IGNORED_SCHEMES = {"data", "blob", "mailto", "tel", "javascript", "about"}
ASSET_EXTENSIONS = {
    ".avif",
    ".css",
    ".eot",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mjs",
    ".mp3",
    ".mp4",
    ".ogg",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".ttf",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
}


@dataclass(frozen=True)
class Reference:
    source_file: str
    source_url: str
    brand: str
    page_path: str
    context: str
    raw_value: str
    dependency: bool


@dataclass(frozen=True)
class Finding:
    brand: str
    page_path: str
    source_file: str
    context: str
    reference: str
    resolved_url: str | None
    resolved_file: str | None
    category: str
    severity: str
    status: int | None
    detail: str


class ReferenceParser(HTMLParser):
    """Collect HTML attributes plus inline CSS and JavaScript."""

    def __init__(self, reference: Reference) -> None:
        super().__init__(convert_charrefs=True)
        self.reference = reference
        self.references: list[Reference] = []
        self._capture_style = False
        self._capture_script = False
        self._style_parts: list[str] = []
        self._script_parts: list[str] = []

    def add(self, context: str, value: str, dependency: bool) -> None:
        if not value.strip():
            return
        self.references.append(
            Reference(
                source_file=self.reference.source_file,
                source_url=self.reference.source_url,
                brand=self.reference.brand,
                page_path=self.reference.page_path,
                context=context,
                raw_value=value.strip(),
                dependency=dependency,
            )
        )

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        rel_tokens = set(attributes.get("rel", "").lower().split())

        if tag == "style":
            self._capture_style = True
            self._style_parts = []
        if tag == "script" and not attributes.get("src"):
            script_type = attributes.get("type", "").lower()
            if script_type in {"", "module", "text/javascript", "application/javascript"}:
                self._capture_script = True
                self._script_parts = []

        if "style" in attributes:
            for value in css_references(attributes["style"]):
                self.add("html:inline-style:url", value, True)

        for attribute in ("src", "poster", "data-src"):
            if attribute in attributes:
                self.add(f"html:{tag}:{attribute}", attributes[attribute], True)

        for attribute in ("srcset", "data-srcset"):
            if attribute in attributes:
                for value in srcset_references(attributes[attribute]):
                    self.add(f"html:{tag}:{attribute}", value, True)

        if "href" not in attributes:
            return

        href = attributes["href"]
        if tag == "link":
            is_metadata = bool(rel_tokens & {"canonical", "alternate", "author"})
            dependency = not is_metadata
            self.add(f"html:link:{','.join(sorted(rel_tokens)) or 'unknown'}", href, dependency)
        elif tag == "a":
            self.add("html:a:href", href, False)
        else:
            self.add(f"html:{tag}:href", href, Path(urlparse(href).path).suffix in ASSET_EXTENSIONS)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "style" and self._capture_style:
            for value in css_references("".join(self._style_parts)):
                self.add("html:style:url", value, True)
            self._capture_style = False
        if tag == "script" and self._capture_script:
            for value in js_references("".join(self._script_parts)):
                self.add("html:script:import", value, True)
            self._capture_script = False

    def handle_data(self, data: str) -> None:
        if self._capture_style:
            self._style_parts.append(data)
        if self._capture_script:
            self._script_parts.append(data)


def css_references(content: str) -> list[str]:
    values = [match.group(2).strip() for match in CSS_URL_RE.finditer(content)]
    values.extend(match.group(1).strip() for match in CSS_IMPORT_RE.finditer(content))
    return values


def js_references(content: str) -> list[str]:
    return [match.group(1).strip() for match in JS_IMPORT_RE.finditer(content)]


def srcset_references(value: str) -> list[str]:
    references: list[str] = []
    for candidate in value.split(","):
        candidate = candidate.strip()
        if candidate:
            references.append(candidate.split()[0])
    return references


def load_catalog(repository: Path) -> tuple[dict, list[tuple[str, dict]]]:
    path = repository / "sites" / "_portal" / "data" / "artifacts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    pages: list[tuple[str, dict]] = []
    for brand, entry in data["brands"].items():
        for page in entry.get("pages", []):
            pages.append((brand, page))
    return data, pages


def preview_url(brand: str, page_path: str) -> str:
    normalized = page_path if page_path.startswith("/") else f"/{page_path}"
    if normalized == "/":
        return f"/site-preview/{brand}/"
    return f"/site-preview/{brand}{normalized}"


def file_for_preview_url(repository: Path, brand: str, url_path: str) -> Path | None:
    prefix = f"/site-preview/{brand}/"
    if url_path == prefix[:-1]:
        url_path = prefix
    if not url_path.startswith(prefix):
        return None

    relative = unquote(url_path[len(prefix) :])
    candidate = repository / "sites" / brand / relative
    if not relative or url_path.endswith("/"):
        candidate /= "index.html"

    try:
        resolved = candidate.resolve()
        brand_root = (repository / "sites" / brand).resolve()
        resolved.relative_to(brand_root)
    except (ValueError, OSError):
        return None
    return resolved


def parse_file(reference: Reference, file_path: Path) -> list[Reference]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="utf-8", errors="replace")

    suffix = file_path.suffix.lower()
    if suffix in {".html", ".htm"}:
        parser = ReferenceParser(reference)
        parser.feed(content)
        return parser.references
    if suffix == ".css":
        return [
            Reference(
                source_file=reference.source_file,
                source_url=reference.source_url,
                brand=reference.brand,
                page_path=reference.page_path,
                context="css:url",
                raw_value=value,
                dependency=True,
            )
            for value in css_references(content)
        ]
    if suffix in {".js", ".mjs"}:
        return [
            Reference(
                source_file=reference.source_file,
                source_url=reference.source_url,
                brand=reference.brand,
                page_path=reference.page_path,
                context="javascript:import",
                raw_value=value,
                dependency=True,
            )
            for value in js_references(content)
        ]
    return []


def http_status(base_url: str, path: str, timeout: float) -> tuple[int | None, str]:
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        headers={"Host": "localhost", "User-Agent": "imperial-preview-asset-crawler/1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, ""
    except HTTPError as error:
        return error.code, str(error)
    except URLError as error:
        return None, str(error.reason)


def classify_reference(
    repository: Path,
    reference: Reference,
    *,
    base_url: str | None,
    timeout: float,
    status_cache: dict[str, tuple[int | None, str]],
) -> tuple[Finding | None, Path | None, str | None]:
    raw = reference.raw_value.strip().strip("\"'")
    parsed = urlparse(raw)

    if not raw or raw.startswith("#") or parsed.scheme.lower() in IGNORED_SCHEMES:
        return None, None, None

    if parsed.scheme in {"http", "https"} or raw.startswith("//"):
        category = "external_runtime_dependency" if reference.dependency else "external_navigation"
        severity = "error" if reference.dependency else "info"
        return (
            Finding(
                brand=reference.brand,
                page_path=reference.page_path,
                source_file=reference.source_file,
                context=reference.context,
                reference=raw,
                resolved_url=raw,
                resolved_file=None,
                category=category,
                severity=severity,
                status=None,
                detail=(
                    "Runtime dependency points to an external origin."
                    if reference.dependency
                    else "External navigation or metadata reference; not loaded by the preview."
                ),
            ),
            None,
            None,
        )

    source_url = reference.source_url
    resolved_url = urljoin(source_url, raw)
    resolved_path = urlparse(resolved_url).path

    if raw.startswith("/assets/"):
        return (
            Finding(
                brand=reference.brand,
                page_path=reference.page_path,
                source_file=reference.source_file,
                context=reference.context,
                reference=raw,
                resolved_url=resolved_path,
                resolved_file=None,
                category="shared_asset_reference",
                severity="error",
                status=None,
                detail="Brand preview references the shared /assets namespace.",
            ),
            None,
            resolved_path,
        )

    expected_prefix = f"/site-preview/{reference.brand}/"
    if raw.startswith("/") and not resolved_path.startswith(expected_prefix):
        return (
            Finding(
                brand=reference.brand,
                page_path=reference.page_path,
                source_file=reference.source_file,
                context=reference.context,
                reference=raw,
                resolved_url=resolved_path,
                resolved_file=None,
                category="invalid_preview_absolute_path",
                severity="error",
                status=None,
                detail=f"Absolute path escapes the brand preview namespace {expected_prefix}.",
            ),
            None,
            resolved_path,
        )

    resolved_file = file_for_preview_url(
        repository, reference.brand, resolved_path
    )
    if resolved_file is None:
        return (
            Finding(
                brand=reference.brand,
                page_path=reference.page_path,
                source_file=reference.source_file,
                context=reference.context,
                reference=raw,
                resolved_url=resolved_path,
                resolved_file=None,
                category="invalid_relative_path",
                severity="error",
                status=None,
                detail="Reference resolves outside the owning brand directory.",
            ),
            None,
            resolved_path,
        )

    relative_file = str(resolved_file.relative_to(repository)).replace("\\", "/")
    if not resolved_file.is_file():
        return (
            Finding(
                brand=reference.brand,
                page_path=reference.page_path,
                source_file=reference.source_file,
                context=reference.context,
                reference=raw,
                resolved_url=resolved_path,
                resolved_file=relative_file,
                category="missing_local_file",
                severity="error",
                status=404,
                detail="Resolved file does not exist.",
            ),
            None,
            resolved_path,
        )

    status: int | None = None
    detail = ""
    if base_url:
        if resolved_path not in status_cache:
            status_cache[resolved_path] = http_status(base_url, resolved_path, timeout)
        status, detail = status_cache[resolved_path]
        if status != 200:
            return (
                Finding(
                    brand=reference.brand,
                    page_path=reference.page_path,
                    source_file=reference.source_file,
                    context=reference.context,
                    reference=raw,
                    resolved_url=resolved_path,
                    resolved_file=relative_file,
                    category="http_not_200",
                    severity="error",
                    status=status,
                    detail=detail or f"Expected HTTP 200, received {status}.",
                ),
                resolved_file,
                resolved_path,
            )

    return (
        Finding(
            brand=reference.brand,
            page_path=reference.page_path,
            source_file=reference.source_file,
            context=reference.context,
            reference=raw,
            resolved_url=resolved_path,
            resolved_file=relative_file,
            category="ok",
            severity="ok",
            status=status,
            detail="Local reference resolved successfully.",
        ),
        resolved_file,
        resolved_path,
    )


def audit(
    repository: Path,
    pages: list[tuple[str, dict]],
    *,
    base_url: str | None,
    timeout: float,
) -> dict:
    findings: list[Finding] = []
    page_results: list[dict] = []
    status_cache: dict[str, tuple[int | None, str]] = {}

    for brand, page in pages:
        page_path = page["path"]
        route = preview_url(brand, page_path)
        file_path = file_for_preview_url(repository, brand, route)
        page_findings: list[Finding] = []

        if file_path is None or not file_path.is_file():
            missing = Finding(
                brand=brand,
                page_path=page_path,
                source_file=str(file_path or ""),
                context="catalog:page",
                reference=page_path,
                resolved_url=route,
                resolved_file=None,
                category="missing_catalog_page",
                severity="error",
                status=404,
                detail="Registered catalog page does not exist.",
            )
            findings.append(missing)
            page_results.append(
                {
                    "brand": brand,
                    "title": page.get("title"),
                    "path": page_path,
                    "route": route,
                    "referenceCount": 0,
                    "errors": 1,
                }
            )
            continue

        relative_page = str(file_path.relative_to(repository)).replace("\\", "/")
        initial = Reference(
            source_file=relative_page,
            source_url=route,
            brand=brand,
            page_path=page_path,
            context="catalog:page",
            raw_value=route,
            dependency=False,
        )

        if base_url:
            status, detail = http_status(base_url, route, timeout)
            status_cache[route] = (status, detail)
            if status != 200:
                page_findings.append(
                    Finding(
                        brand=brand,
                        page_path=page_path,
                        source_file=relative_page,
                        context="catalog:page",
                        reference=page_path,
                        resolved_url=route,
                        resolved_file=relative_page,
                        category="http_not_200",
                        severity="error",
                        status=status,
                        detail=detail or f"Expected HTTP 200, received {status}.",
                    )
                )

        queue: deque[tuple[Reference, Path]] = deque([(initial, file_path)])
        parsed_resources: set[tuple[Path, str]] = set()
        references_seen: set[tuple[str, str, str]] = set()

        while queue:
            source_reference, source_file = queue.popleft()
            resource_key = (source_file, source_reference.source_url)
            if resource_key in parsed_resources:
                continue
            parsed_resources.add(resource_key)

            for reference in parse_file(source_reference, source_file):
                reference_key = (
                    reference.source_url,
                    reference.context,
                    reference.raw_value,
                )
                if reference_key in references_seen:
                    continue
                references_seen.add(reference_key)

                finding, resolved_file, resolved_url = classify_reference(
                    repository,
                    reference,
                    base_url=base_url,
                    timeout=timeout,
                    status_cache=status_cache,
                )
                if finding is not None:
                    page_findings.append(finding)

                if (
                    resolved_file
                    and resolved_url
                    and resolved_file.suffix.lower() in {".css", ".js", ".mjs"}
                ):
                    queue.append(
                        (
                            Reference(
                                source_file=str(
                                    resolved_file.relative_to(repository)
                                ).replace("\\", "/"),
                                source_url=resolved_url,
                                brand=brand,
                                page_path=page_path,
                                context="recursive:asset",
                                raw_value=resolved_url,
                                dependency=True,
                            ),
                            resolved_file,
                        )
                    )

        findings.extend(page_findings)
        page_results.append(
            {
                "brand": brand,
                "title": page.get("title"),
                "path": page_path,
                "route": route,
                "referenceCount": len(references_seen),
                "errors": sum(item.severity == "error" for item in page_findings),
                "warnings": sum(item.severity == "warning" for item in page_findings),
                "externalNavigation": sum(
                    item.category == "external_navigation" for item in page_findings
                ),
            }
        )

    counts = Counter(item.category for item in findings)
    severities = Counter(item.severity for item in findings)
    by_brand: dict[str, dict] = {}
    grouped_pages: dict[str, list[dict]] = defaultdict(list)
    for page in page_results:
        grouped_pages[page["brand"]].append(page)

    for brand, brand_pages in grouped_pages.items():
        brand_findings = [item for item in findings if item.brand == brand]
        by_brand[brand] = {
            "pageCount": len(brand_pages),
            "availablePages": sum(page["errors"] == 0 for page in brand_pages),
            "missingPages": [
                page["path"]
                for page in brand_pages
                if any(
                    item.brand == brand
                    and item.page_path == page["path"]
                    and item.category in {"missing_catalog_page", "missing_local_file"}
                    for item in brand_findings
                )
            ],
            "errorCount": sum(item.severity == "error" for item in brand_findings),
            "findingCounts": dict(Counter(item.category for item in brand_findings)),
        }

    return {
        "meta": {
            "schemaVersion": 1,
            "catalogPageCount": len(pages),
            "baseUrl": base_url,
            "runtimeExternalDependenciesAllowed": False,
        },
        "summary": {
            "errors": severities["error"],
            "warnings": severities["warning"],
            "okReferences": severities["ok"],
            "externalNavigation": counts["external_navigation"],
            "categories": dict(sorted(counts.items())),
        },
        "brands": by_brand,
        "pages": page_results,
        "findings": [asdict(item) for item in findings],
    }


def write_markdown(report: dict, path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# Website preview asset audit",
        "",
        f"- Katalógusoldalak: **{report['meta']['catalogPageCount']}**",
        f"- Hibák: **{summary['errors']}**",
        f"- Sikeres helyi hivatkozások: **{summary['okReferences']}**",
        f"- Külső navigációk/meta-hivatkozások: **{summary['externalNavigation']}**",
        "",
        "## Márkánként",
        "",
        "| Márka | Oldal | Elérhető | Hiányzó | Hibák |",
        "|---|---:|---:|---:|---:|",
    ]
    for brand, values in sorted(report["brands"].items()):
        lines.append(
            f"| {brand} | {values['pageCount']} | {values['availablePages']} | "
            f"{len(values['missingPages'])} | {values['errorCount']} |"
        )

    errors = [
        finding
        for finding in report["findings"]
        if finding["severity"] == "error"
    ]
    lines.extend(["", "## Blokkoló hibák", ""])
    if not errors:
        lines.append("Nincs blokkoló asset- vagy útvonalhiba.")
    else:
        lines.extend(
            [
                "| Márka | Oldal | Kategória | Hivatkozás | Részlet |",
                "|---|---|---|---|---|",
            ]
        )
        for finding in errors:
            reference = finding["reference"].replace("|", "\\|")
            detail = finding["detail"].replace("|", "\\|")
            lines.append(
                f"| {finding['brand']} | `{finding['page_path']}` | "
                f"`{finding['category']}` | `{reference}` | {detail} |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--base-url")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--expected-pages", type=int)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument(
        "--allow-errors",
        action="store_true",
        help="Write the report but do not fail when blocking findings exist.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    repository = args.repository.resolve()
    _, pages = load_catalog(repository)
    report = audit(
        repository,
        pages,
        base_url=args.base_url,
        timeout=args.timeout,
    )

    if args.expected_pages is not None and len(pages) != args.expected_pages:
        report["summary"]["errors"] += 1
        report["findings"].append(
            asdict(
                Finding(
                    brand="_catalog",
                    page_path="",
                    source_file="sites/_portal/data/artifacts.json",
                    context="catalog",
                    reference=str(len(pages)),
                    resolved_url=None,
                    resolved_file=None,
                    category="unexpected_catalog_page_count",
                    severity="error",
                    status=None,
                    detail=f"Expected {args.expected_pages} pages, found {len(pages)}.",
                )
            )
        )

    if args.json_output:
        output = args.json_output
        if not output.is_absolute():
            output = repository / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.markdown_output:
        output = args.markdown_output
        if not output.is_absolute():
            output = repository / output
        write_markdown(report, output)

    summary = report["summary"]
    print(
        json.dumps(
            {
                "pages": report["meta"]["catalogPageCount"],
                "errors": summary["errors"],
                "okReferences": summary["okReferences"],
                "categories": summary["categories"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if args.allow_errors or summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
