from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from .schemas import GrowthSignalIn


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceBatch:
    signals: list[GrowthSignalIn]
    raw_count: int

    @property
    def rejected_count(self) -> int:
        return self.raw_count - len(self.signals)


def _nested(value: Any, path: str) -> Any:
    current = value
    for part in path.split(".") if path else []:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _text(value: Any) -> str:
    return str(value or "").strip()


def _timestamp(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(str(value))
        except (TypeError, ValueError) as exc:
            raise SourceError("Source item contains an invalid timestamp") from exc
    return result if result.tzinfo else result.replace(tzinfo=UTC)


def _same_host(url: str, allowed_hosts: list[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname not in allowed_hosts:
        raise SourceError("Source URL host is not allowlisted")


def fetch_source(source_id: str, source: dict[str, Any], *, limit: int) -> SourceBatch:
    url = str(source["url"])
    allowed_hosts = [
        str(host).lower() for host in source.get("allowed_hosts") or [urlparse(url).hostname]
    ]
    _same_host(url, allowed_hosts)
    try:
        with httpx.Client(
            timeout=float(source.get("timeout_seconds", 20)), follow_redirects=False
        ) as client:
            response = client.get(url, headers={"User-Agent": "Imperial-Growth-Ops/1.0"})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceError(f"Source request failed: {type(exc).__name__}") from exc
    if len(response.content) > int(source.get("max_response_bytes", 5_000_000)):
        raise SourceError("Source response exceeds the configured limit")
    kind = str(source.get("kind"))
    if kind == "json":
        return _json_items(source_id, source, response, limit=limit)
    if kind == "rss":
        return _rss_items(source_id, source, response, limit=limit)
    raise SourceError(f"Unsupported source kind: {kind}")


def _json_items(
    source_id: str, source: dict[str, Any], response: httpx.Response, *, limit: int
) -> SourceBatch:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SourceError("Source returned invalid JSON") from exc
    items = (
        _nested(payload, str(source.get("items_path") or ""))
        if source.get("items_path")
        else payload
    )
    if not isinstance(items, list):
        raise SourceError("Configured JSON items path is not a list")
    mapping = source.get("field_map") or {}
    result: list[GrowthSignalIn] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        canonical = {key: _nested(item, str(path)) for key, path in mapping.items()}
        canonical.update(source.get("defaults") or {})
        canonical["source_id"] = source_id
        canonical["motor_key"] = source["motor"]
        canonical["source_bucket"] = source["bucket"]
        canonical["detected_at"] = _timestamp(canonical.get("detected_at"))
        canonical["source_payload_hash"] = hashlib.sha256(
            json.dumps(item, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        try:
            result.append(GrowthSignalIn.model_validate(canonical))
        except Exception:
            continue
    return SourceBatch(signals=result, raw_count=min(len(items), limit))


def _rss_items(
    source_id: str, source: dict[str, Any], response: httpx.Response, *, limit: int
) -> SourceBatch:
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise SourceError("Source returned invalid RSS/Atom XML") from exc
    entries = root.findall(".//item") or root.findall(".//{*}entry")
    defaults = source.get("defaults") or {}
    result: list[GrowthSignalIn] = []
    for entry in entries[:limit]:
        values: dict[str, str] = {}
        for child in list(entry):
            name = child.tag.rsplit("}", 1)[-1]
            values[name] = _text(child.text or child.attrib.get("href"))
        link = values.get("link") or values.get("guid")
        if not link or not link.startswith("https://"):
            continue
        canonical = {
            **defaults,
            "source_id": source_id,
            "external_key": values.get("guid") or link,
            "motor_key": source["motor"],
            "source_bucket": source["bucket"],
            "signal_type": defaults.get("signal_type") or source["bucket"],
            "detected_at": _timestamp(
                values.get("updated") or values.get("published") or values.get("pubDate")
            ),
            "subject_type": defaults.get("subject_type", "organization"),
            "recipient_email_type": "none",
            "contact_basis": "unknown",
            "summary": values.get("description")
            or values.get("summary")
            or values.get("title")
            or "Forrásolt üzleti jelzés.",
            "evidence_url": link,
            "confidence": int(defaults.get("confidence", 50)),
            "urgency": int(defaults.get("urgency", 50)),
        }
        canonical["source_payload_hash"] = hashlib.sha256(
            json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        try:
            result.append(GrowthSignalIn.model_validate(canonical))
        except Exception:
            continue
    return SourceBatch(signals=result, raw_count=min(len(entries), limit))
