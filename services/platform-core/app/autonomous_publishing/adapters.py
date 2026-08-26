from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import io
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from uuid import uuid4

from PIL import Image

from .http import ProductionHttpClient, PublishingHttpError
from .registry import Binding, RegistryError
from .schemas import PublicationJobIn


class AdapterError(RuntimeError):
    pass


class ReadbackError(AdapterError):
    pass


@dataclass
class AdapterResult:
    external_id: str
    public_url: str
    admin_url: str | None
    content_hash: str
    canonical_url: str | None
    readback: dict[str, Any]
    published_at: datetime


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def json_response(response) -> dict[str, Any]:
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise AdapterError("adapter returned non-JSON response") from exc
    if not isinstance(body, dict):
        raise AdapterError("adapter response must be a JSON object")
    return body


def _image_factory_asset(
    payload: dict[str, Any], *, default_role: str
) -> tuple[bytes, str, str]:
    reference = payload.get("image_factory")
    if not isinstance(reference, dict):
        raise AdapterError("Image Factory asset reference is missing")
    job_id = str(reference.get("job_id") or "")
    role = str(reference.get("role") or default_role)
    expected_sha256 = str(reference.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
        raise AdapterError("Image Factory job ID is invalid")
    if role not in {"web_hero", "open_graph", "square", "facebook"}:
        raise AdapterError("Image Factory asset role is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise AdapterError("Image Factory expected SHA-256 is invalid")
    token = os.getenv("IMAGE_FACTORY_API_TOKEN", "").strip()
    if len(token) < 32:
        raise AdapterError("Image Factory API token is missing")
    host = os.getenv("CONTENT_IMAGE_FACTORY_HOST", "image-factory").strip()
    port = int(os.getenv("CONTENT_IMAGE_FACTORY_PORT", "8000"))
    connection = http.client.HTTPConnection(host, port, timeout=30)
    try:
        connection.request(
            "GET",
            f"/api/v1/jobs/{job_id}/assets/{role}",
            headers={"X-API-Key": token, "Accept": "image/*"},
        )
        response = connection.getresponse()
        raw = response.read(25 * 1024 * 1024 + 1)
        headers = {key.casefold(): value for key, value in response.getheaders()}
    finally:
        connection.close()
    if response.status != 200:
        raise AdapterError(f"Image Factory asset download failed: HTTP {response.status}")
    if len(raw) > 25 * 1024 * 1024:
        raise AdapterError("Image Factory asset exceeds the size limit")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256 or headers.get("x-content-sha256") != expected_sha256:
        raise AdapterError("Image Factory asset SHA-256 verification failed")
    if headers.get("x-release-state") != "TEST_ONLY_REVIEW_REQUIRED":
        raise AdapterError("Image Factory release state is invalid")
    media_type = headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise AdapterError("Image Factory asset MIME type is invalid")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
    except Exception as exc:
        raise AdapterError("Image Factory asset is not a valid image") from exc
    return raw, media_type, actual_sha256


class BaseAdapter:
    channel: str

    def __init__(self, binding: Binding, client: ProductionHttpClient) -> None:
        self.binding = binding
        self.client = client

    def preflight(self, job: PublicationJobIn) -> None:
        if self.binding.brand_id != job.brand_id or self.binding.channel != self.channel:
            raise RegistryError("brand/channel binding mismatch")

    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        raise NotImplementedError

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        raise NotImplementedError


class NIMAdapter(BaseAdapter):
    channel = "nim_cms"

    REQUIRED_CONTRACT_KEYS = {
        "create_path",
        "read_path",
        "publish_path",
        "disable_path",
        "field_map",
        "readback_map",
        "signing_headers",
    }

    def preflight(self, job: PublicationJobIn) -> None:
        super().preflight(job)
        contract = self.binding.config.get("contract")
        if not isinstance(contract, dict) or self.REQUIRED_CONTRACT_KEYS - set(contract):
            raise RegistryError("verified NIM API contract is incomplete")
        if not self.binding.secret.get("hmac_secret"):
            raise RegistryError("NIM HMAC secret is missing")
        required_fields = {
            "content_asset_id",
            "content_version_id",
            "title",
            "slug",
            "language",
            "main_category",
            "body_html",
            "visual_asset_package_id",
            "seo_title",
            "meta_description",
            "canonical_url",
            "robots",
            "cta",
            "enabled",
        }
        if required_fields - set(contract["field_map"]):
            raise RegistryError("NIM field mapping does not cover mandatory contract fields")
        readback_map = contract["readback_map"]
        if not (
            readback_map.get("visual_asset_package_id")
            or readback_map.get("featured_image_url")
        ):
            raise RegistryError("NIM visual readback mapping is missing")

    def _headers(self, method: str, path: str, payload: dict[str, Any], key: str) -> dict[str, str]:
        contract = self.binding.config["contract"]
        timestamp = str(int(time.time()))
        body_hash = sha(payload)
        signing = "\n".join([timestamp, method.upper(), path, body_hash, key])
        signature = hmac.new(
            str(self.binding.secret["hmac_secret"]).encode(), signing.encode(), hashlib.sha256
        ).hexdigest()
        names = contract["signing_headers"]
        return {
            str(names["timestamp"]): timestamp,
            str(names["idempotency"]): key,
            str(names["content_hash"]): body_hash,
            str(names["signature"]): signature,
        }

    def _payload(self, job: PublicationJobIn) -> dict[str, Any]:
        source = {
            "content_asset_id": job.content_asset_id,
            "content_version_id": job.content_version_id,
            "brand_id": job.brand_id,
            "title": job.title,
            "slug": job.canonical_slug,
            "language": job.language,
            "main_category": job.categories[0] if job.categories else None,
            "additional_categories": job.categories[1:],
            "tags": job.tags,
            "author": job.author,
            "body_html": job.body_html,
            "visual_asset_package_id": job.visual_asset_package_id,
            "publish_at": job.desired_publish_at.isoformat() if job.desired_publish_at else None,
            "seo_title": job.seo_title or job.title,
            "meta_description": job.meta_description or job.excerpt,
            "canonical_url": job.canonical_url,
            "robots": "index,follow",
            "cta": job.cta,
            "enabled": False,
            **job.channel_payloads.get(self.channel, {}),
        }
        field_map = self.binding.config["contract"]["field_map"]
        return {str(target): source.get(source_name) for source_name, target in field_map.items()}

    def _readback(self, job: PublicationJobIn, external_id: str, key: str) -> AdapterResult:
        contract = self.binding.config["contract"]
        path = str(contract["read_path"]).format(external_id=quote(external_id))
        response = self.client.request(
            self.channel,
            "GET",
            urljoin(self.binding.config["base_url"], path),
            headers=self._headers("GET", path, {}, key),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-readback",
            idempotency_key=key,
        )
        data = json_response(response)
        mapping = contract["readback_map"]

        def value(name: str):
            return data.get(mapping[name])

        if str(value("external_id")) != external_id:
            raise ReadbackError("NIM external ID mismatch")
        if str(value("content_asset_id")) != job.content_asset_id:
            raise ReadbackError("NIM ContentAssetID mismatch")
        if str(value("content_version_id")) != job.content_version_id:
            raise ReadbackError("NIM content version mismatch")
        if str(value("content_hash")) != job.content_hash:
            raise ReadbackError("NIM content hash mismatch")
        if str(value("title")).strip() != job.title.strip():
            raise ReadbackError("NIM title mismatch")
        visual_id_field = mapping.get("visual_asset_package_id")
        visual_url_field = mapping.get("featured_image_url")
        if visual_id_field:
            if str(data.get(visual_id_field) or "") != job.visual_asset_package_id:
                raise ReadbackError("NIM visual asset readback mismatch")
        elif visual_url_field:
            if not str(data.get(visual_url_field) or "").startswith("https://"):
                raise ReadbackError("NIM featured image readback missing")
        else:
            raise ReadbackError("NIM visual readback mapping missing at runtime")
        if not bool(value("public_visible")) or not bool(value("enabled")):
            raise ReadbackError("NIM public visibility is not proven")
        public_url = str(value("public_url") or "")
        if not public_url.startswith("https://"):
            raise ReadbackError("NIM public URL missing")
        self.client.request(
            self.channel,
            "GET",
            public_url,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-public",
            max_attempts=3,
        )
        return AdapterResult(
            external_id=external_id,
            public_url=public_url,
            admin_url=str(value("admin_url") or "") or None,
            content_hash=job.content_hash,
            canonical_url=str(value("canonical_url") or "") or public_url,
            readback=data,
            published_at=datetime.now(UTC),
        )

    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        self.preflight(job)
        contract = self.binding.config["contract"]
        payload = self._payload(job)
        create_path = str(contract["create_path"])
        created = json_response(
            self.client.request(
                self.channel,
                "POST",
                urljoin(self.binding.config["base_url"], create_path),
                headers=self._headers("POST", create_path, payload, key),
                json_body=payload,
                correlation_id=job.correlation_id,
                request_id=f"{job.job_id}-nim-create",
                idempotency_key=key,
            )
        )
        external_id = str(created.get(contract.get("create_id_field", "id")) or "")
        if not external_id:
            raise AdapterError("NIM create did not return object ID")
        publish_path = str(contract["publish_path"]).format(external_id=quote(external_id))
        publish_payload = {str(contract.get("enable_field", "enabled")): True}
        self.client.request(
            self.channel,
            "POST",
            urljoin(self.binding.config["base_url"], publish_path),
            headers=self._headers("POST", publish_path, publish_payload, key),
            json_body=publish_payload,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-publish",
            idempotency_key=key,
        )
        return self._readback(job, external_id, key)

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        contract = self.binding.config["contract"]
        path = str(contract["disable_path"]).format(external_id=quote(result.external_id))
        payload = {str(contract.get("enable_field", "enabled")): False, "reason": reason}
        response = self.client.request(
            self.channel,
            "POST",
            urljoin(self.binding.config["base_url"], path),
            headers=self._headers("POST", path, payload, sha({"rollback": job.idempotency_key})),
            json_body=payload,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-rollback",
            idempotency_key=sha({"rollback": job.idempotency_key}),
        )
        readback = self._readback_disabled(job, result.external_id)
        return {
            "rollback_id": response.headers.get("X-Rollback-ID") or f"RB-{uuid4().hex}",
            "readback": readback,
        }

    def _readback_disabled(self, job: PublicationJobIn, external_id: str) -> dict[str, Any]:
        contract = self.binding.config["contract"]
        path = str(contract["read_path"]).format(external_id=quote(external_id))
        response = self.client.request(
            self.channel,
            "GET",
            urljoin(self.binding.config["base_url"], path),
            headers=self._headers("GET", path, {}, job.idempotency_key),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-rollback-readback",
        )
        data = json_response(response)
        enabled_field = contract["readback_map"]["enabled"]
        if bool(data.get(enabled_field)):
            raise ReadbackError("NIM rollback readback still reports enabled")
        return data


class _NIMAdminEditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}
        self.selected: dict[str, str] = {}
        self.options: dict[str, list[str]] = {}
        self.current_textarea: str | None = None
        self.current_select: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        tag = tag.casefold()
        name = str(values.get("name") or "")
        if tag == "input" and name:
            self.values[name] = str(values.get("value") or "")
        elif tag == "textarea" and name:
            self.current_textarea = name
            self.values[name] = ""
        elif tag == "select" and name:
            self.current_select = name
        elif tag == "option" and self.current_select:
            option = str(values.get("value") or "")
            self.options.setdefault(self.current_select, []).append(option)
            if "selected" in values:
                self.selected[self.current_select] = option

    def handle_data(self, data: str) -> None:
        if self.current_textarea:
            self.values[self.current_textarea] += data

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "textarea":
            self.current_textarea = None
        elif tag == "select":
            self.current_select = None


class NIMAdminSessionAdapter(BaseAdapter):
    """Verified legacy NIM admin-session route with live readback and rollback."""

    channel = "nim_cms"
    REQUIRED_CONFIG_KEYS = {
        "base_url",
        "login_submit_path",
        "create_path",
        "read_path",
        "disable_path",
        "default_category_id",
    }

    @staticmethod
    def _origin(value: str) -> str:
        parsed = urlparse(value)
        return f"{parsed.scheme}://{parsed.netloc}"

    def preflight(self, job: PublicationJobIn) -> None:
        super().preflight(job)
        if self.binding.config.get("mode") != "admin_session_live":
            raise RegistryError("NIM admin-session mode is not live")
        if self.REQUIRED_CONFIG_KEYS - set(self.binding.config):
            raise RegistryError("verified NIM admin-session contract is incomplete")
        if not all(self.binding.secret.get(name) for name in ("login_url", "username", "password")):
            raise RegistryError("NIM admin-session credentials are incomplete")
        if self._origin(str(self.binding.secret["login_url"])) != self._origin(
            str(self.binding.config["base_url"])
        ):
            raise RegistryError("NIM login origin does not match the bound site")
        payload = job.channel_payloads.get(self.channel, {})
        if payload.get("publish_live") is not True:
            raise RegistryError("NIM admin-session route requires explicit live publication")
        if not str(payload.get("featured_image_id") or "").strip() and not isinstance(
            payload.get("image_factory"), dict
        ):
            raise RegistryError(
                "NIM live publication requires a featured image because the public article template fails without one"
            )
        if set(job.channels) != {self.channel}:
            raise RegistryError("NIM live publication must be a standalone channel job")
        category_id = str(self.binding.config["default_category_id"])
        if not category_id.isdigit() or int(category_id) < 1:
            raise RegistryError("NIM default category ID is invalid")

    def _login(self, job: PublicationJobIn, key: str) -> None:
        login_url = str(self.binding.secret["login_url"])
        self.client.request(
            self.channel,
            "GET",
            login_url,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-login-form",
            idempotency_key=key,
        )
        response = self.client.request(
            self.channel,
            "POST",
            urljoin(
                str(self.binding.config["base_url"]),
                str(self.binding.config["login_submit_path"]),
            ),
            data={
                "params[email]": str(self.binding.secret["username"]),
                "params[password]": str(self.binding.secret["password"]),
                "redirect": "/admin_site",
            },
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-login",
            idempotency_key=key,
        )
        if "params[password]" in response.text:
            raise AdapterError("NIM admin-session login was not accepted")

    def _load_article_form(self, job: PublicationJobIn, key: str) -> None:
        response = self.client.request(
            self.channel,
            "GET",
            urljoin(str(self.binding.config["base_url"]), "/admin_article/add"),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-add-form",
            idempotency_key=key,
        )
        parser = _NIMAdminEditParser()
        parser.feed(response.text)
        if "params[hu_HU]" not in parser.values:
            raise AdapterError("NIM admin article form is not available")
        configured_category = str(self.binding.config.get("default_category_id") or "")
        # NIM loads primary-category options through JavaScript after the initial
        # form response, so absence from this static HTML is not evidence that the
        # configured category is invalid. Registry preflight already validates the
        # configured numeric ID; retain it here.
        category = configured_category
        authors = [
            value for value in parser.options.get("params[user_public]", []) if value
        ]
        configured_author = str(self.binding.config.get("default_author_id") or "")
        author = configured_author if configured_author in authors else (authors[0] if authors else "")
        self._article_form_defaults = {"category": category, "author": author}

    def _upload_featured_image(self, job: PublicationJobIn, key: str) -> str:
        channel_payload = job.channel_payloads[self.channel]
        existing = str(channel_payload.get("featured_image_id") or "").strip()
        if existing:
            return existing
        raw, media_type, content_sha256 = _image_factory_asset(
            channel_payload, default_role="web_hero"
        )
        suffix = ".png" if media_type == "image/png" else ".webp" if media_type == "image/webp" else ".jpg"
        safe_asset = re.sub(r"[^a-z0-9-]+", "-", job.content_asset_id.casefold()).strip("-")
        filename = f"content-factory-{safe_asset[:80]}-{content_sha256[:12]}{suffix}"
        relative_path = f"content/{filename}"
        public_url = urljoin(str(self.binding.config["base_url"]), relative_path)
        try:
            existing_response = self.client.request(
                self.channel,
                "GET",
                public_url,
                correlation_id=job.correlation_id,
                request_id=f"{job.job_id}-nim-image-existing",
                idempotency_key=key,
            )
        except PublishingHttpError as exc:
            if exc.status != 404:
                raise
        else:
            if hashlib.sha256(existing_response.content).hexdigest() == content_sha256:
                return relative_path
            raise AdapterError("NIM image path already exists with different content")
        upload = self.client.request(
            self.channel,
            "POST",
            urljoin(str(self.binding.config["base_url"]), "/admin_filemanager/upload"),
            data={"dir": "content"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": urljoin(
                    str(self.binding.config["base_url"]), "/admin_filemanager/dialog"
                ),
                "Origin": str(self.binding.config["base_url"]).rstrip("/"),
            },
            files={"file": (filename, raw, media_type)},
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-image-upload",
            idempotency_key=sha({"key": key, "image_sha256": content_sha256}),
        )
        if upload.status_code != 200:
            raise AdapterError("NIM image upload was not accepted")
        verify = self.client.request(
            self.channel,
            "GET",
            public_url,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-image-verify",
            idempotency_key=key,
        )
        if hashlib.sha256(verify.content).hexdigest() != content_sha256:
            raise AdapterError("NIM uploaded image SHA-256 verification failed")
        return relative_path

    def _article_payload(self, job: PublicationJobIn) -> dict[str, Any]:
        channel_payload = job.channel_payloads[self.channel]
        defaults = getattr(self, "_article_form_defaults", {})
        return {
            "redirect": urljoin(str(self.binding.config["base_url"]), "/admin_article/add"),
            # NIM's save_new endpoint fails with HTTP 500 when a record is
            # created enabled. Create it disabled, then use the admin enable
            # endpoint once the exact new ID has been discovered.
            "params[enable]": "0",
            # The legacy NIM form renders these SEO/language selects with empty
            # values. Sending synthetic values makes save_new fail with HTTP 500.
            "params[language]": "",
            "params[hu_HU]": job.title,
            "params[hu_HU_url]": job.canonical_slug,
            "params[hu_HU_title]": job.seo_title or job.title,
            "params[hu_HU_text]": job.body_html,
            "params[hu_HU_metadescription]": job.meta_description or job.excerpt,
            "params[hu_HU_customscript]": "",
            "params[hu_HU_robots_type]": "",
            "params[hu_HU_robots]": "",
            "params[hu_HU_canonical]": job.canonical_url or "",
            "params[categorie]": str(defaults.get("category") or ""),
            "params[categories]": "",
            "params[categories][]": "",
            "params[user_public]": str(defaults.get("author") or ""),
            "params[date_public]": datetime.now(UTC).date().isoformat(),
            "params[date_start]": "",
            "params[date_end]": "",
            "params[image]": str(
                getattr(self, "_uploaded_featured_image_id", "")
                or channel_payload.get("featured_image_id")
                or ""
            ),
            "params[related][]": "",
            "params[labels]": "",
            "params[labels][]": "",
            "params[images]": "",
            "params[images][]": "",
        }

    def _find_created_article_id(self, job: PublicationJobIn, key: str) -> str:
        search_url = urljoin(
            str(self.binding.config["base_url"]),
            f"/admin_article/page?key={quote(job.canonical_slug)}",
        )
        response = self.client.request(
            self.channel,
            "GET",
            search_url,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-created-lookup",
            idempotency_key=key,
        )
        for row in re.findall(r"<tr\b[^>]*>.*?</tr>", response.text, flags=re.I | re.S):
            if job.canonical_slug not in row:
                continue
            match = re.search(r"/admin_article/(?:edit/)?(\d+)(?:[/?#\"']|$)", row)
            if not match:
                match = re.search(
                    r"name=[\"']id[\"'][^>]*value=[\"'](\d+)[\"']",
                    row,
                    flags=re.I,
                )
            if match:
                return match.group(1)
        raise AdapterError("NIM admin creation succeeded without a discoverable article ID")

    def _readback_live(self, job: PublicationJobIn, external_id: str) -> AdapterResult:
        path = str(self.binding.config["read_path"]).format(external_id=quote(external_id))
        response = self.client.request(
            self.channel,
            "GET",
            urljoin(str(self.binding.config["base_url"]), path),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-live-readback",
            idempotency_key=job.idempotency_key,
        )
        parser = _NIMAdminEditParser()
        parser.feed(response.text)
        if parser.values.get("params[hu_HU]", "").strip() != job.title.strip():
            raise ReadbackError("NIM admin live title mismatch")
        if parser.values.get("params[hu_HU_url]", "").strip() != job.canonical_slug:
            raise ReadbackError("NIM admin live slug mismatch")
        if parser.values.get("params[hu_HU_text]", "").strip() != job.body_html.strip():
            raise ReadbackError("NIM admin live body mismatch")
        if parser.selected.get("params[enable]") != "1":
            raise ReadbackError("NIM article is not enabled")
        admin_url = urljoin(str(self.binding.config["base_url"]), path)
        public_prefix = str(self.binding.config.get("public_path_prefix") or "/blog/")
        public_url = urljoin(
            str(self.binding.config["base_url"]),
            f"{public_prefix.rstrip('/')}/{job.canonical_slug}",
        )
        public_response = self.client.request(
            self.channel,
            "GET",
            public_url,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-public-readback",
            idempotency_key=job.idempotency_key,
        )
        if job.title not in public_response.text:
            raise ReadbackError("NIM public page title is not visible")
        featured_image_present = bool(parser.values.get("params[image]", "").strip())
        return AdapterResult(
            external_id=external_id,
            public_url=public_url,
            admin_url=admin_url,
            content_hash=job.content_hash,
            canonical_url=public_url,
            readback={
                "draft_only": False,
                "enabled": True,
                "title_verified": True,
                "slug_verified": True,
                "body_verified": True,
                "public_title_verified": True,
                "featured_image_present": featured_image_present,
                "image_required_followup": not featured_image_present,
            },
            published_at=datetime.now(UTC),
        )

    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        self.preflight(job)
        self._login(job, key)
        self._uploaded_featured_image_id = self._upload_featured_image(job, key)
        self._load_article_form(job, key)
        response = self.client.request(
            self.channel,
            "POST",
            urljoin(
                str(self.binding.config["base_url"]),
                str(self.binding.config["create_path"]),
            ),
            data=self._article_payload(job),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-create-live",
            idempotency_key=key,
        )
        location = str(response.headers.get("Location") or "")
        match = re.search(r"/admin_article/(?:edit/)?(\d+)(?:[/?#]|$)", location)
        if not match:
            match = re.search(r"admin_article/(?:edit/)?(\d+)", response.text)
        external_id = match.group(1) if match else self._find_created_article_id(job, key)
        self.client.request(
            self.channel,
            "POST",
            urljoin(str(self.binding.config["base_url"]), str(self.binding.config["disable_path"])),
            data={
                "id": external_id,
                "value": "1",
                "redirect": urljoin(
                    str(self.binding.config["base_url"]),
                    str(self.binding.config["read_path"]).format(external_id=external_id),
                ),
            },
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-enable-live",
            idempotency_key=key,
        )
        return self._readback_live(job, external_id)

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        response = self.client.request(
            self.channel,
            "POST",
            urljoin(str(self.binding.config["base_url"]), str(self.binding.config["disable_path"])),
            data={"id": result.external_id, "value": "0", "redirect": "/admin_article"},
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-nim-admin-disable",
            idempotency_key=job.idempotency_key,
        )
        return {
            "rollback_id": f"RB-{uuid4().hex}",
            "readback": {"disabled": True, "response_received": response is not None},
            "action": "disabled_live_article",
            "reason": reason,
        }


class WordPressAdapter(BaseAdapter):
    channel = "wordpress"

    def preflight(self, job: PublicationJobIn) -> None:
        super().preflight(job)
        if not self.binding.secret.get("username") or not self.binding.secret.get(
            "application_password"
        ):
            raise RegistryError("WordPress application access is missing")

    def _headers(self) -> dict[str, str]:
        credentials = (
            f"{self.binding.secret['username']}:{self.binding.secret['application_password']}"
        )
        raw = credentials.encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}

    def _url(self, path: str) -> str:
        return urljoin(self.binding.config["base_url"].rstrip("/") + "/", path.lstrip("/"))

    def _resolve_terms(self, job: PublicationJobIn, taxonomy: str, values: list[str]) -> list[int]:
        ids: list[int] = []
        for value in values:
            if str(value).isdigit():
                ids.append(int(value))
                continue
            response = self.client.request(
                self.channel,
                "GET",
                self._url(f"wp-json/wp/v2/{taxonomy}?slug={quote(value)}&per_page=2"),
                headers=self._headers(),
                correlation_id=job.correlation_id,
                request_id=f"{job.job_id}-wp-{taxonomy}-{sha(value)[:8]}",
            )
            body = response.json()
            if not isinstance(body, list) or len(body) != 1 or not body[0].get("id"):
                raise AdapterError(f"WordPress {taxonomy} resolution is ambiguous: {value}")
            ids.append(int(body[0]["id"]))
        return ids

    def _upload_media(self, job: PublicationJobIn, key: str) -> int | None:
        media = job.channel_payloads.get(self.channel, {}).get("media")
        if not media:
            raise AdapterError("WordPress media payload is required")
        url = str(media.get("url") or "")
        if not url.startswith("https://"):
            raise AdapterError("WordPress media URL must use HTTPS")
        response = self.client.request(
            self.channel,
            "GET",
            url,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-wp-media-download",
        )
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        allowed = {"image/jpeg", "image/png", "image/webp"}
        if content_type not in allowed:
            raise AdapterError("WordPress media MIME is not allowlisted")
        max_bytes = int(self.binding.config.get("max_media_bytes", 10_000_000))
        if len(response.content) > max_bytes:
            raise AdapterError("WordPress media exceeds file size limit")
        try:
            with Image.open(io.BytesIO(response.content)) as image:
                width, height = image.size
        except Exception as exc:
            raise AdapterError("WordPress media image validation failed") from exc
        minimum = self.binding.config.get("min_image_dimensions", [600, 315])
        if width < int(minimum[0]) or height < int(minimum[1]):
            raise AdapterError("WordPress media dimensions are too small")
        filename = str(media.get("filename") or f"{job.content_asset_id}.jpg")
        upload = self.client.request(
            self.channel,
            "POST",
            self._url("wp-json/wp/v2/media"),
            headers={
                **self._headers(),
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
            files={"file": (filename, response.content, content_type)},
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-wp-media-upload",
            idempotency_key=sha({"key": key, "media": job.visual_asset_package_id}),
        )
        body = json_response(upload)
        if not body.get("id"):
            raise AdapterError("WordPress media upload did not return media ID")
        return int(body["id"])

    def _readback(self, job: PublicationJobIn, post_id: str) -> AdapterResult:
        response = self.client.request(
            self.channel,
            "GET",
            self._url(f"wp-json/wp/v2/posts/{quote(post_id)}?context=edit"),
            headers=self._headers(),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-wp-readback",
        )
        data = json_response(response)
        if str(data.get("id")) != post_id or data.get("status") not in {"publish", "future"}:
            raise ReadbackError("WordPress post ID or publication status mismatch")
        raw_content = str((data.get("content") or {}).get("raw") or "")
        if (
            hashlib.sha256(raw_content.encode()).hexdigest()
            != hashlib.sha256(job.body_html.encode()).hexdigest()
        ):
            raise ReadbackError("WordPress content hash mismatch")
        if str((data.get("title") or {}).get("raw") or "").strip() != job.title.strip():
            raise ReadbackError("WordPress title mismatch")
        if int(data.get("featured_media") or 0) <= 0:
            raise ReadbackError("WordPress featured image readback missing")
        public_url = str(data.get("link") or "")
        if not public_url.startswith("https://"):
            raise ReadbackError("WordPress permalink missing")
        public = self.client.request(
            self.channel,
            "GET",
            public_url,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-wp-public-readback",
        )
        if job.title not in public.text:
            raise ReadbackError("WordPress public page title readback mismatch")
        return AdapterResult(
            external_id=post_id,
            public_url=public_url,
            admin_url=self._url(f"wp-admin/post.php?post={quote(post_id)}&action=edit"),
            content_hash=job.content_hash,
            canonical_url=job.canonical_url or public_url,
            readback=data,
            published_at=datetime.now(UTC),
        )

    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        self.preflight(job)
        featured_media = self._upload_media(job, key)
        status = "future" if job.desired_publish_at else "publish"
        payload = {
            "title": job.title,
            "slug": job.canonical_slug,
            "content": job.body_html,
            "excerpt": job.excerpt,
            "status": status,
            "date_gmt": job.desired_publish_at.isoformat() if job.desired_publish_at else None,
            "categories": self._resolve_terms(job, "categories", job.categories),
            "tags": self._resolve_terms(job, "tags", job.tags),
            "featured_media": featured_media or 0,
            **job.channel_payloads.get(self.channel, {}).get("post", {}),
        }
        response = self.client.request(
            self.channel,
            "POST",
            self._url("wp-json/wp/v2/posts"),
            headers=self._headers(),
            json_body=payload,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-wp-publish",
            idempotency_key=key,
        )
        data = json_response(response)
        post_id = str(data.get("id") or "")
        if not post_id:
            raise AdapterError("WordPress publish did not return post ID")
        return self._readback(job, post_id)

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        response = self.client.request(
            self.channel,
            "POST",
            self._url(f"wp-json/wp/v2/posts/{quote(result.external_id)}"),
            headers=self._headers(),
            json_body={"status": "draft"},
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-wp-rollback",
            idempotency_key=sha({"rollback": job.idempotency_key}),
        )
        data = json_response(response)
        verify = json_response(
            self.client.request(
                self.channel,
                "GET",
                self._url(f"wp-json/wp/v2/posts/{quote(result.external_id)}?context=edit"),
                headers=self._headers(),
                correlation_id=job.correlation_id,
                request_id=f"{job.job_id}-wp-rollback-readback",
            )
        )
        if verify.get("status") != "draft":
            raise ReadbackError("WordPress rollback readback did not return draft")
        return {
            "rollback_id": f"RB-WP-{result.external_id}",
            "response": data,
            "readback": verify,
            "reason": reason,
        }


class MetaAdapter(BaseAdapter):
    def __init__(self, binding: Binding, client: ProductionHttpClient, channel: str) -> None:
        self.channel = channel
        super().__init__(binding, client)

    def preflight(self, job: PublicationJobIn) -> None:
        super().preflight(job)
        if not self.binding.secret.get("access_token"):
            raise RegistryError("Meta managed access token is missing")
        if self.channel == "facebook" and not self.binding.config.get("page_id"):
            raise RegistryError("Facebook Page binding is missing")
        if self.channel == "instagram" and not self.binding.config.get("instagram_account_id"):
            raise RegistryError("Instagram account binding is missing")

    def _url(self, path: str) -> str:
        version = str(self.binding.config.get("api_version") or "")
        if not version.startswith("v"):
            raise RegistryError("Pinned Meta Graph API version is required")
        return urljoin(
            self.binding.config["base_url"].rstrip("/") + "/", f"{version}/{path.lstrip('/')}"
        )

    def _auth(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {**(payload or {}), "access_token": self.binding.secret["access_token"]}

    def _readback(self, job: PublicationJobIn, external_id: str) -> AdapterResult:
        fields = (
            "id,permalink_url,created_time,message,is_published,full_picture"
            if self.channel == "facebook"
            else "id,permalink,caption,media_type,media_url,timestamp"
        )
        response = self.client.request(
            self.channel,
            "GET",
            self._url(quote(external_id)),
            params=self._auth({"fields": fields}),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-{self.channel}-readback",
        )
        data = json_response(response)
        if str(data.get("id") or "") != external_id:
            raise ReadbackError("Meta external ID mismatch")
        expected_copy = str(
            job.channel_payloads.get(self.channel, {}).get(
                "message" if self.channel == "facebook" else "caption"
            )
            or job.excerpt
        )
        if (
            self.channel == "facebook"
            and job.canonical_url
            and job.canonical_url not in expected_copy
        ):
            expected_copy = f"{expected_copy}\\n\\n{job.canonical_url}"
        actual_copy = str(data.get("message" if self.channel == "facebook" else "caption") or "")
        if actual_copy.strip() != expected_copy.strip():
            raise ReadbackError("Meta content readback mismatch")
        permalink = str(data.get("permalink_url") or data.get("permalink") or "")
        if not permalink.startswith("https://"):
            raise ReadbackError("Meta permalink missing")
        if self.channel == "facebook" and data.get("is_published") is False:
            raise ReadbackError("Facebook post is not public")
        if self.channel == "facebook" and not str(data.get("full_picture") or "").startswith("https://"):
            raise ReadbackError("Facebook image readback missing")
        if self.channel == "instagram" and not str(data.get("media_url") or "").startswith("https://"):
            raise ReadbackError("Instagram image readback missing")
        return AdapterResult(
            external_id=external_id,
            public_url=permalink,
            admin_url=None,
            content_hash=job.content_hash,
            canonical_url=job.canonical_url,
            readback=data,
            published_at=datetime.now(UTC),
        )

    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        self.preflight(job)
        payload = job.channel_payloads.get(self.channel, {})
        canonical = job.canonical_url
        if self.channel == "facebook":
            page_id = str(self.binding.config["page_id"])
            message = str(payload.get("message") or job.excerpt)
            if canonical and canonical not in message:
                message = f"{message}\n\n{canonical}"
            if isinstance(payload.get("image_factory"), dict):
                raw, media_type, content_sha256 = _image_factory_asset(
                    payload, default_role="facebook"
                )
                suffix = (
                    ".png"
                    if media_type == "image/png"
                    else ".webp"
                    if media_type == "image/webp"
                    else ".jpg"
                )
                created = json_response(
                    self.client.request(
                        self.channel,
                        "POST",
                        self._url(f"{quote(page_id)}/photos"),
                        data=self._auth({"message": message, "published": True}),
                        files={
                            "source": (
                                f"{job.content_asset_id}-{content_sha256[:12]}{suffix}",
                                raw,
                                media_type,
                            )
                        },
                        correlation_id=job.correlation_id,
                        request_id=f"{job.job_id}-facebook-photo-publish",
                        idempotency_key=key,
                    )
                )
                external_id = str(created.get("post_id") or created.get("id") or "")
                if not external_id:
                    raise AdapterError("Facebook photo publish did not return object ID")
                return self._readback(job, external_id)
            image_url = str(payload.get("image_url") or "")
            if not image_url.startswith("https://"):
                raise AdapterError("Facebook image_factory or HTTPS image_url is required")
            created = json_response(
                self.client.request(
                    self.channel,
                    "POST",
                    self._url(f"{quote(page_id)}/photos"),
                    data=self._auth(
                        {
                            "url": image_url,
                            "caption": message,
                            "published": "true",
                        }
                    ),
                    correlation_id=job.correlation_id,
                    request_id=f"{job.job_id}-facebook-photo-publish",
                    idempotency_key=key,
                )
            )
            external_id = str(created.get("post_id") or created.get("id") or "")
        else:
            if not canonical or not canonical.startswith("https://"):
                raise AdapterError("Verified canonical web URL is required before Instagram publish")
            account_id = str(self.binding.config["instagram_account_id"])
            image_url = str(payload.get("image_url") or "")
            if not image_url.startswith("https://"):
                raise AdapterError("Instagram HTTPS image_url is required")
            container = json_response(
                self.client.request(
                    self.channel,
                    "POST",
                    self._url(f"{quote(account_id)}/media"),
                    data=self._auth(
                        {"image_url": image_url, "caption": payload.get("caption") or job.excerpt}
                    ),
                    correlation_id=job.correlation_id,
                    request_id=f"{job.job_id}-instagram-container",
                    idempotency_key=sha({"key": key, "step": "container"}),
                )
            )
            container_id = str(container.get("id") or "")
            if not container_id:
                raise AdapterError("Instagram container ID missing")
            deadline = time.monotonic() + int(
                self.binding.config.get("container_timeout_seconds", 120)
            )
            while time.monotonic() < deadline:
                status = json_response(
                    self.client.request(
                        self.channel,
                        "GET",
                        self._url(quote(container_id)),
                        params=self._auth({"fields": "status_code,status"}),
                        correlation_id=job.correlation_id,
                        request_id=f"{job.job_id}-instagram-container-status",
                    )
                )
                code = str(status.get("status_code") or "")
                if code == "FINISHED":
                    break
                if code in {"ERROR", "EXPIRED"}:
                    raise AdapterError(f"Instagram container failed: {code}")
                time.sleep(2)
            else:
                raise AdapterError("Instagram container timeout")
            published = json_response(
                self.client.request(
                    self.channel,
                    "POST",
                    self._url(f"{quote(account_id)}/media_publish"),
                    data=self._auth({"creation_id": container_id}),
                    correlation_id=job.correlation_id,
                    request_id=f"{job.job_id}-instagram-publish",
                    idempotency_key=sha({"key": key, "step": "publish"}),
                )
            )
            external_id = str(published.get("id") or "")
        if not external_id:
            raise AdapterError("Meta publish did not return object ID")
        return self._readback(job, external_id)

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        response = self.client.request(
            self.channel,
            "DELETE",
            self._url(quote(result.external_id)),
            data=self._auth(),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-{self.channel}-rollback",
            idempotency_key=sha({"rollback": job.idempotency_key, "channel": self.channel}),
        )
        data = json_response(response)
        if data.get("success") is not True:
            raise AdapterError("Meta delete did not confirm success")
        try:
            self._readback(job, result.external_id)
        except PublishingHttpError as exc:
            if exc.status not in {400, 404}:
                raise
        else:
            raise ReadbackError("Meta rollback readback still finds object")
        return {
            "rollback_id": f"RB-META-{result.external_id}",
            "response": data,
            "readback": {"deleted": True},
            "reason": reason,
        }


class EventAdapter(BaseAdapter):
    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        self.preflight(job)
        payload = {
            "event_type": "PUBLICATION_READBACK_VERIFIED",
            "job_id": job.job_id,
            "content_asset_id": job.content_asset_id,
            "content_version_id": job.content_version_id,
            "brand_id": job.brand_id,
            "canonical_url": job.canonical_url,
            "correlation_id": job.correlation_id,
            **job.channel_payloads.get(self.channel, {}),
        }
        response = self.client.request(
            self.channel,
            "POST",
            str(self.binding.config["event_url"]),
            headers={"Authorization": f"Bearer {self.binding.secret['token']}"},
            json_body=payload,
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-{self.channel}-event",
            idempotency_key=key,
        )
        data = json_response(response)
        external_id = str(data.get("event_id") or data.get("id") or "")
        if not external_id:
            raise AdapterError(f"{self.channel} event ID missing")
        read_url = str(self.binding.config["read_path"]).format(external_id=quote(external_id))
        readback = json_response(
            self.client.request(
                self.channel,
                "GET",
                urljoin(str(self.binding.config["base_url"]), read_url),
                headers={"Authorization": f"Bearer {self.binding.secret['token']}"},
                correlation_id=job.correlation_id,
                request_id=f"{job.job_id}-{self.channel}-readback",
            )
        )
        if str(readback.get("event_id") or readback.get("id") or "") != external_id:
            raise ReadbackError(f"{self.channel} event readback mismatch")
        return AdapterResult(
            external_id=external_id,
            public_url=job.canonical_url or "internal://event",
            admin_url=None,
            content_hash=job.content_hash,
            canonical_url=job.canonical_url,
            readback=readback,
            published_at=datetime.now(UTC),
        )

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        return {
            "rollback_id": f"RB-EVENT-{result.external_id}",
            "readback": {"immutable_event": True},
            "reason": reason,
        }


class ForumDraftAdapter(BaseAdapter):
    channel = "forum"

    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        self.preflight(job)
        if str(self.binding.config.get("mode") or "draft_only") != "draft_only":
            raise AdapterError(
                "Forum auto-post requires separately verified policy and official API"
            )
        draft_id = f"FORUM-DRAFT-{sha({'job': job.job_id, 'key': key})[:20].upper()}"
        return AdapterResult(
            external_id=draft_id,
            public_url="internal://forum-draft",
            admin_url=None,
            content_hash=job.content_hash,
            canonical_url=job.canonical_url,
            readback={"draft_id": draft_id, "mode": "draft_only", "readback": True},
            published_at=datetime.now(UTC),
        )

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        return {
            "rollback_id": f"RB-{result.external_id}",
            "readback": {"deleted": True},
            "reason": reason,
        }


def build_adapter(binding: Binding, client: ProductionHttpClient) -> BaseAdapter:
    if binding.channel == "nim_cms":
        if binding.config.get("mode") == "admin_session_live":
            return NIMAdminSessionAdapter(binding, client)
        return NIMAdapter(binding, client)
    if binding.channel == "wordpress":
        return WordPressAdapter(binding, client)
    if binding.channel in {"facebook", "instagram"}:
        return MetaAdapter(binding, client, binding.channel)
    if binding.channel in {"analytics", "crm"}:
        adapter = EventAdapter(binding, client)
        adapter.channel = binding.channel
        return adapter
    if binding.channel == "forum":
        return ForumDraftAdapter(binding, client)
    raise RegistryError(f"Unsupported channel adapter: {binding.channel}")
