from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse, urlunparse

GENERIC_PATH_SEGMENTS = {
    "",
    "blog",
    "blogs",
    "category",
    "categories",
    "cimke",
    "forum",
    "about",
    "adatvedelem",
    "adatkezeles",
    "contact",
    "kapcsolat",
    "rolunk",
    "privacy",
    "forums",
    "hirek",
    "index",
    "kereses",
    "search",
    "tag",
    "tags",
    "tema",
    "temak",
    "topic",
    "topics",
}
LISTING_QUERY_KEYS = {
    "filter",
    "keyword",
    "keywords",
    "offset",
    "page",
    "paged",
    "pageno",
    "q",
    "query",
    "s",
    "search",
    "sort",
}
ALLOWED_CONTENT_FORMATS = {"article", "social_post", "faq"}
PUBLIC_CHANNELS = {"nim_cms", "wordpress", "facebook", "instagram"}
WEB_CHANNELS = {"nim_cms", "wordpress"}
SOCIAL_CHANNELS = {"facebook", "instagram"}


class PublicationIntegrityError(ValueError):
    """Fail-closed validation error for daily content and publication evidence."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_id(prefix: str, *parts: str, length: int = 20) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest().upper()
    return f"{prefix}{digest[:length]}"


def _normalise_url(value: str) -> str:
    try:
        parsed = urlparse(value.strip())
        host = (parsed.hostname or "").lower()
        port = f":{parsed.port}" if parsed.port else ""
    except (TypeError, ValueError) as exc:
        raise PublicationIntegrityError("invalid_source_url") from exc
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), host + port, path, "", parsed.query, ""))


def is_exact_post_permalink(value: str | None) -> bool:
    """Return True only for a specific, public HTTPS content URL, not a listing/search URL."""
    if not value or len(value) > 1500:
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False
    if parsed.fragment:
        return False
    if any(
        key.casefold() in LISTING_QUERY_KEYS
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    ):
        return False
    segments = [segment.casefold() for segment in parsed.path.split("/") if segment]
    if not segments:
        return False
    if segments[-1] in GENERIC_PATH_SEGMENTS:
        return False
    if any(segment in {"page", "oldal", "pagination"} for segment in segments):
        return False
    # A single short generic-looking path is normally a landing page, not a concrete post.
    if len(segments) == 1 and (len(segments[0]) < 8 or segments[0] in GENERIC_PATH_SEGMENTS):
        return False
    slug = segments[-1]
    if not re.search(r"[a-z0-9áéíóöőúüű]", slug, flags=re.IGNORECASE):
        return False
    return True


def validate_question_permalink(
    *,
    route_url: str,
    candidate_url: str | None,
    source_text: str,
) -> str:
    """Validate a literal question's exact source permalink.

    A search/category/forum index URL is never accepted. A permalink extracted from a listing
    must be literally present in the captured source text and stay on the same host.
    """
    raw_candidate = str(candidate_url or route_url).strip()
    # Search/listing pages often expose relative href values; resolve them against the
    # captured route before validating the exact public permalink.
    candidate = _normalise_url(urljoin(route_url, raw_candidate))
    route = _normalise_url(route_url)
    if not is_exact_post_permalink(candidate):
        raise PublicationIntegrityError("exact_post_permalink_missing")
    candidate_host = (urlparse(candidate).hostname or "").lower()
    route_host = (urlparse(route).hostname or "").lower()
    same_site = (
        candidate_host == route_host
        or candidate_host.endswith("." + route_host)
        or route_host.endswith("." + candidate_host)
    )
    if not same_site:
        raise PublicationIntegrityError("source_permalink_host_mismatch")
    if candidate != route and candidate not in source_text and raw_candidate not in source_text:
        raise PublicationIntegrityError("source_permalink_not_observed_literal")
    return candidate


def validate_content_package(
    package: Mapping[str, Any],
    *,
    expected_brand: str,
    allowed_urls: Iterable[str],
    minimum_body_chars: int = 300,
) -> dict[str, Any]:
    """Validate and normalise one brand package without affecting any other brand."""
    if not isinstance(package, Mapping):
        raise PublicationIntegrityError("package_not_object")
    brand = str(package.get("brand_id") or "").strip()
    if brand != expected_brand:
        raise PublicationIntegrityError("brand_id_mismatch")
    title = " ".join(str(package.get("title") or "").split())
    body = str(package.get("body") or "").strip()
    content_format = str(package.get("format") or "").strip()
    if len(title) < 8:
        raise PublicationIntegrityError("title_too_short")
    if len(body) < minimum_body_chars:
        raise PublicationIntegrityError("body_too_short")
    if content_format not in ALLOWED_CONTENT_FORMATS:
        raise PublicationIntegrityError("invalid_content_format")
    allowed = {_normalise_url(url) for url in allowed_urls if url}
    raw_urls = package.get("source_urls") or []
    if not isinstance(raw_urls, list):
        raise PublicationIntegrityError("source_urls_not_list")
    source_urls: list[str] = []
    for raw in raw_urls:
        if not isinstance(raw, str):
            raise PublicationIntegrityError("source_url_not_string")
        normalised = _normalise_url(raw)
        if normalised not in allowed:
            raise PublicationIntegrityError("unsupplied_source_url")
        if normalised not in source_urls:
            source_urls.append(normalised)
    return {
        "brand_id": expected_brand,
        "title": title,
        "format": content_format,
        "body": body,
        "source_urls": source_urls,
    }


@dataclass(frozen=True)
class BrandGenerationResult:
    brand_id: str
    status: str
    package: dict[str, Any] | None
    attempts: int
    errors: tuple[str, ...]
    request_id: str | None = None


def generate_brand_isolated(
    *,
    brand_id: str,
    allowed_urls: Iterable[str],
    generator: Callable[[str, int], tuple[Mapping[str, Any], str | None]],
    max_attempts: int = 3,
) -> BrandGenerationResult:
    """Retry a single brand in isolation. One malformed response cannot poison 18 others."""
    if max_attempts < 1 or max_attempts > 5:
        raise ValueError("max_attempts must be between 1 and 5")
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            raw, request_id = generator(brand_id, attempt)
            package = validate_content_package(
                raw,
                expected_brand=brand_id,
                allowed_urls=allowed_urls,
            )
            return BrandGenerationResult(
                brand_id=brand_id,
                status="quarantined",
                package=package,
                attempts=attempt,
                errors=tuple(errors),
                request_id=request_id,
            )
        except Exception as exc:  # caller records only error type; no secrets or raw payloads
            errors.append(type(exc).__name__ + ":" + str(exc)[:160])
    return BrandGenerationResult(
        brand_id=brand_id,
        status="failed",
        package=None,
        attempts=max_attempts,
        errors=tuple(errors),
    )


@dataclass(frozen=True)
class PublicationObservation:
    brand_id: str
    channel: str
    state: str
    public_url: str | None
    proof_id: str | None
    image_verified: bool


@dataclass(frozen=True)
class DailyIntegrityResult:
    status: str
    expected: int
    verified: int
    missing: tuple[str, ...]
    invalid: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "healthy"


def evaluate_daily_publication_integrity(
    *,
    expected_routes: Mapping[str, Sequence[str]],
    observations: Iterable[PublicationObservation],
) -> DailyIntegrityResult:
    """Fail closed unless every expected brand/channel has image and public readback proof."""
    rows = list(observations)
    observed: dict[tuple[str, str], PublicationObservation] = {}
    duplicate_keys: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.brand_id, row.channel)
        if key in observed:
            duplicate_keys.add(key)
        observed[key] = row
    missing: list[str] = []
    invalid: list[str] = [
        f"{brand}/{channel}:duplicate_observation"
        for brand, channel in sorted(duplicate_keys)
    ]
    verified = 0
    expected = 0
    for brand, channels in sorted(expected_routes.items()):
        web_channels = [channel for channel in channels if channel in WEB_CHANNELS]
        if len(web_channels) != 1:
            invalid.append(f"{brand}:cms_route_count={len(web_channels)}")
        for channel in sorted(set(channels)):
            if channel not in PUBLIC_CHANNELS:
                continue
            expected += 1
            key = f"{brand}/{channel}"
            row = observed.get((brand, channel))
            if row is None:
                missing.append(key)
                continue
            if row.state != "READBACK_VERIFIED":
                invalid.append(f"{key}:state={row.state}")
                continue
            if not row.public_url or not row.public_url.startswith("https://"):
                invalid.append(f"{key}:public_permalink_missing")
                continue
            if not row.proof_id:
                invalid.append(f"{key}:proof_missing")
                continue
            if not row.image_verified:
                invalid.append(f"{key}:image_not_verified")
                continue
            verified += 1
    status = (
        "healthy"
        if expected > 0 and verified == expected and not missing and not invalid
        else "degraded"
    )
    return DailyIntegrityResult(
        status=status,
        expected=expected,
        verified=verified,
        missing=tuple(sorted(missing)),
        invalid=tuple(sorted(invalid)),
    )
