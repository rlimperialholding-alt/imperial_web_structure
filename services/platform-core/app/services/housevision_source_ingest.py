from __future__ import annotations

import hashlib
import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import struct
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from ..config import settings
from .fs_guard import contained_path


MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024
IMAGE_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
FLOORPLAN_WORDS = (
    "alaprajz",
    "floorplan",
    "floor-plan",
    "floor_plan",
    "rzut",
    "grundriss",
    "parter",
    "poddasze",
    # The Imperial Holding catalogue uses this product-specific filename for
    # the dimensioned plan image instead of the usual "alaprajz" token.
    "oldalhataros",
)
NOISE_WORDS = (
    "logo",
    "favicon",
    "icon",
    "seal",
    "certif",
    "instagram",
    "facebook",
    "banner",
    "avatar",
    "placeholder",
)


class SourceIngestError(ValueError):
    pass


@dataclass(frozen=True)
class AssetCandidate:
    url: str
    label: str
    score: int
    asset_type: str


@dataclass(frozen=True)
class IngestedAsset:
    source_url: str
    asset_type: str
    content_sha256: str
    width_px: int
    height_px: int
    magic_mime_type: str
    storage_ref: str
    label: str


def _public_addresses(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        results = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SourceIngestError("A forrásdomain nem oldható fel.") from exc
    addresses = {ipaddress.ip_address(item[4][0]) for item in results}
    if not addresses or any(not address.is_global for address in addresses):
        raise SourceIngestError("Privát, loopback, link-local vagy reserved cél tiltott.")
    return addresses


def _canonical_https(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise SourceIngestError("Kizárólag publikus HTTPS-forrás fogadható.")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise SourceIngestError("Userinfo és egyedi port tiltott.")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise SourceIngestError("Belső vagy metadata host tiltott.")
    path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="=&%:@!$'()*+,;/?-._~")
    return urlunsplit(("https", host, path, query, ""))


def _same_rights_domain(source_url: str, target_url: str) -> bool:
    source_host = (urlsplit(source_url).hostname or "").lower().removeprefix("www.")
    target_host = (urlsplit(target_url).hostname or "").lower().removeprefix("www.")
    return target_host == source_host or target_host.endswith("." + source_host)


def _fetch(url: str, *, accept: str, max_bytes: int, source_url: str) -> tuple[str, bytes, str]:
    current = _canonical_https(url)
    for _ in range(4):
        if not _same_rights_domain(source_url, current):
            raise SourceIngestError("A forrásoldal jogi domainjén kívüli asset tiltott.")
        parsed = urlsplit(current)
        host = parsed.hostname or ""
        allowed = _public_addresses(host)
        context = ssl.create_default_context()
        # Publikus provider-fetch: kizárólag igazolt TLS 1.2+; SSL és TLS 1.0/1.1 tiltott.
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
            host, port=443, timeout=30, context=context
        )
        try:
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            connection.request(
                "GET",
                target,
                headers={
                    "User-Agent": "Imperial-HouseVision-SourceIngest/1.1",
                    "Accept": accept,
                },
            )
            response = connection.getresponse()
            peer = ipaddress.ip_address(connection.sock.getpeername()[0]) if connection.sock else None
            if peer not in allowed or not peer.is_global:
                raise SourceIngestError("DNS/IP újraellenőrzés sikertelen.")
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise SourceIngestError("Üres redirect cél.")
                current = _canonical_https(urljoin(current, location))
                continue
            if response.status != 200:
                raise SourceIngestError(f"A forrás HTTP {response.status} választ adott.")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise SourceIngestError("A letöltés túllépi a biztonsági méretlimitet.")
                chunks.append(chunk)
            return current, b"".join(chunks), (response.getheader("Content-Type") or "").lower()
        finally:
            connection.close()
    raise SourceIngestError("Túl sok redirect.")


class _GalleryParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.raw: list[tuple[str, str, int]] = []
        self.title = ""
        self._in_title = False
        self._video_figure = False
        self._video_anchor = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "figure" and "image_video" in data.get("class", "").lower().split():
            self._video_figure = True
        if tag.lower() == "a" and data.get("data-type", "").lower() == "video":
            self._video_anchor = True
        if tag.lower() == "base" and data.get("href"):
            self.base_url = urljoin(self.base_url, data["href"])
            return
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() not in {"img", "source", "a"}:
            return
        # Video poster frames are not independent architectural evidence and
        # must never be registered as exterior source views.
        if self._video_figure or self._video_anchor:
            return
        label = " ".join(
            data.get(key, "") for key in ("alt", "title", "class", "id", "aria-label")
        ).strip()
        values: list[tuple[str, int]] = []
        for key, bonus in (("data-src", 55), ("data-original", 50), ("href", 35), ("src", 25)):
            value = data.get(key, "").strip()
            if value:
                values.append((value, bonus))
        for key in ("srcset", "data-srcset"):
            for item in data.get(key, "").split(","):
                value = item.strip().split(" ", 1)[0]
                if value:
                    values.append((value, 5))
        for value, bonus in values:
            self.raw.append((urljoin(self.base_url, html.unescape(value)), label, bonus))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() == "a":
            self._video_anchor = False
        if tag.lower() == "figure":
            self._video_figure = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def discover_asset_candidates(body: bytes, final_url: str, limit: int) -> list[AssetCandidate]:
    parser = _GalleryParser(final_url)
    parser.feed(body.decode("utf-8", errors="replace"))
    slug = (urlsplit(final_url).path.rstrip("/").split("/")[-1] or "").lower()
    title_words = {
        word for word in re.findall(r"[a-z0-9áéíóöőúüű-]{3,}", parser.title.lower())
        if word not in {"ház", "house", "projekt", "imperial", "holding"}
    }
    best: dict[str, AssetCandidate] = {}
    for raw_url, label, source_bonus in parser.raw:
        try:
            url = _canonical_https(raw_url)
        except SourceIngestError:
            continue
        if not _same_rights_domain(final_url, url):
            continue
        haystack = (url + " " + label).lower()
        path = urlsplit(url).path.lower()
        if not re.search(r"\.(?:jpe?g|png|webp)$", path):
            continue
        # Product pages also contain recommendation carousels for unrelated
        # houses.  A source candidate must be bound to the current product slug.
        if slug and slug not in haystack:
            continue
        floorplan = any(word in haystack for word in FLOORPLAN_WORDS)
        score = source_bonus + (120 if floorplan else 0)
        if slug and slug in haystack:
            score += 55
        if title_words and any(word in haystack for word in title_words):
            score += 25
        if any(word in haystack for word in ("tipushaz", "typehouse", "project", "projekt", "gallery")):
            score += 20
        if "content_cache" in haystack or re.search(r"-\d{2,4}\.(?:jpe?g|png|webp)$", path):
            score -= 35
        if any(word in haystack for word in NOISE_WORDS):
            score -= 150
        if score < 55:
            continue
        candidate = AssetCandidate(
            url=url,
            label=label,
            score=score,
            asset_type="FLOORPLAN" if floorplan else "EXTERIOR",
        )
        existing = best.get(url)
        if not existing or candidate.score > existing.score:
            best[url] = candidate
    ordered = sorted(best.values(), key=lambda item: (-item.score, item.url))
    selected: list[AssetCandidate] = []
    seen_stems: set[str] = set()
    for item in ordered:
        stem = re.sub(r"-\d{2,4}$", "", Path(urlsplit(item.url).path).stem.lower())
        key = f"{item.asset_type}:{stem}"
        if key in seen_stems:
            continue
        seen_stems.add(key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _image_identity(payload: bytes) -> tuple[str, int, int]:
    if payload.startswith(b"\x89PNG\r\n\x1a\n") and len(payload) >= 24:
        width, height = struct.unpack(">II", payload[16:24])
        return "image/png", width, height
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP" and len(payload) >= 30:
        kind = payload[12:16]
        if kind == b"VP8X":
            width = 1 + int.from_bytes(payload[24:27], "little")
            height = 1 + int.from_bytes(payload[27:30], "little")
            return "image/webp", width, height
        if kind == b"VP8L" and payload[20] == 0x2F:
            bits = int.from_bytes(payload[21:25], "little")
            return "image/webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if payload.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(payload):
            if payload[offset] != 0xFF:
                offset += 1
                continue
            marker = payload[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(payload):
                break
            size = int.from_bytes(payload[offset:offset + 2], "big")
            if size < 2 or offset + size > len(payload):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height = int.from_bytes(payload[offset + 3:offset + 5], "big")
                width = int.from_bytes(payload[offset + 5:offset + 7], "big")
                return "image/jpeg", width, height
            offset += size
    raise SourceIngestError("A fájl magic-byte vagy képméret ellenőrzése sikertelen.")


def ingest_page_assets(source_url: str, job_id: str, limit: int) -> tuple[list[IngestedAsset], dict]:
    final_url, body, content_type = _fetch(
        source_url,
        accept="text/html,application/xhtml+xml",
        max_bytes=MAX_HTML_BYTES,
        source_url=source_url,
    )
    if "html" not in content_type:
        raise SourceIngestError("A forrás nem HTML tartalom.")
    candidates = discover_asset_candidates(body, final_url, limit)
    # A job_id felhasználói paraméter: csak kanonikus feloldás és konténment-
    # ellenőrzés után kerülhet a fájlrendszerre (traversal/symlink fail-closed).
    target = contained_path(Path(settings.typehouse_factory_asset_root) / "legacy", job_id)
    target = target / "source"
    target.mkdir(parents=True, exist_ok=True)
    accepted: list[IngestedAsset] = []
    skipped: list[dict[str, str]] = []
    seen_hashes: set[str] = set()
    for item in candidates:
        try:
            resolved, payload, _ = _fetch(
                item.url,
                accept="image/jpeg,image/png,image/webp",
                max_bytes=MAX_IMAGE_BYTES,
                source_url=final_url,
            )
            mime, width, height = _image_identity(payload)
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            path = target / f"{len(accepted) + 1:02d}-{digest[:16]}.{IMAGE_MIME[mime]}"
            path.write_bytes(payload)
            accepted.append(
                IngestedAsset(
                    source_url=resolved,
                    asset_type=item.asset_type,
                    content_sha256=digest,
                    width_px=width,
                    height_px=height,
                    magic_mime_type=mime,
                    storage_ref=str(path),
                    label=item.label,
                )
            )
        except (SourceIngestError, OSError, ValueError) as exc:
            skipped.append({"url": item.url, "reason": str(exc)})
    report = {
        "schema_version": "1.0",
        "job_id": job_id,
        "source_url": source_url,
        "final_url": final_url,
        "source_html_sha256": hashlib.sha256(body).hexdigest(),
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "accepted": [item.__dict__ for item in accepted],
        "skipped": skipped,
    }
    (target.parent / "source-ingest-manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    return accepted, report
