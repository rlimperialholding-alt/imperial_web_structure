from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urljoin
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
            return None
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
            "id,permalink_url,created_time,message,is_published"
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
        actual_copy = str(data.get("message" if self.channel == "facebook" else "caption") or "")
        if actual_copy.strip() != expected_copy.strip():
            raise ReadbackError("Meta content readback mismatch")
        permalink = str(data.get("permalink_url") or data.get("permalink") or "")
        if not permalink.startswith("https://"):
            raise ReadbackError("Meta permalink missing")
        if self.channel == "facebook" and data.get("is_published") is False:
            raise ReadbackError("Facebook post is not public")
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
        if not canonical or not canonical.startswith("https://"):
            raise AdapterError("Verified canonical web URL is required before social publish")
        if self.channel == "facebook":
            page_id = str(self.binding.config["page_id"])
            body = self._auth(
                {
                    "message": payload.get("message") or job.excerpt,
                    "link": canonical,
                    "published": True,
                }
            )
            created = json_response(
                self.client.request(
                    self.channel,
                    "POST",
                    self._url(f"{quote(page_id)}/feed"),
                    data=body,
                    correlation_id=job.correlation_id,
                    request_id=f"{job.job_id}-facebook-publish",
                    idempotency_key=key,
                )
            )
            external_id = str(created.get("id") or "")
        else:
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


class LinkedInAdapter(BaseAdapter):
    channel = "linkedin"

    def preflight(self, job: PublicationJobIn) -> None:
        super().preflight(job)
        if not self.binding.secret.get("access_token"):
            raise RegistryError("LinkedIn managed access token is missing")
        scopes = self.binding.secret.get("granted_scopes")
        if not isinstance(scopes, list) or "w_organization_social" not in scopes:
            raise RegistryError("LinkedIn w_organization_social scope is not proven")
        organization_id = str(self.binding.config.get("organization_id") or "")
        if not organization_id.isdigit() or organization_id.startswith("0"):
            raise RegistryError("LinkedIn organization binding is missing")
        version = str(self.binding.config.get("api_version") or "")
        if len(version) != 6 or not version.isdigit():
            raise RegistryError("Pinned LinkedIn API version is required")
        slug = str(self.binding.config.get("public_slug") or "")
        if slug and any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in slug
        ):
            raise RegistryError("LinkedIn public page slug is invalid")

    def _headers(self, *, method: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.binding.secret['access_token']}",
            "Linkedin-Version": str(self.binding.config["api_version"]),
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }
        if method:
            headers["X-RestLi-Method"] = method
        return headers

    def _url(self, path: str) -> str:
        return urljoin(self.binding.config["base_url"].rstrip("/") + "/", path.lstrip("/"))

    def _author(self) -> str:
        return f"urn:li:organization:{self.binding.config['organization_id']}"

    def _commentary(self, job: PublicationJobIn) -> str:
        payload = job.channel_payloads.get(self.channel, {})
        commentary = str(payload.get("commentary") or "").strip()
        canonical = str(job.canonical_url or "").strip()
        if not canonical.startswith("https://"):
            raise AdapterError("Verified canonical web URL is required before LinkedIn publish")
        if canonical not in commentary:
            commentary = f"{commentary}\n\n{canonical}".strip()
        if not commentary or len(commentary) > 3000:
            raise AdapterError("LinkedIn commentary is missing or exceeds 3000 characters")
        return commentary

    def _post_payload(self, job: PublicationJobIn) -> dict[str, Any]:
        channel_payload = job.channel_payloads.get(self.channel, {})
        payload: dict[str, Any] = {
            "author": self._author(),
            "commentary": self._commentary(job),
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": bool(
                channel_payload.get("is_reshare_disabled_by_author", False)
            ),
        }
        media_urn = channel_payload.get("media_urn")
        if media_urn:
            payload["content"] = {
                "media": {
                    "id": str(media_urn),
                    "title": str(channel_payload.get("media_title") or job.title),
                }
            }
        return payload

    def _readback(self, job: PublicationJobIn, external_id: str) -> AdapterResult:
        response = self.client.request(
            self.channel,
            "GET",
            self._url(f"rest/posts/{quote(external_id, safe='')}"),
            headers=self._headers(),
            params={"viewContext": "READER"},
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-linkedin-readback",
        )
        data = json_response(response)
        if str(data.get("author") or "") != self._author():
            raise ReadbackError("LinkedIn organization author mismatch")
        if str(data.get("commentary") or "").strip() != self._commentary(job):
            raise ReadbackError("LinkedIn commentary readback mismatch")
        if data.get("lifecycleState") != "PUBLISHED" or data.get("visibility") != "PUBLIC":
            raise ReadbackError("LinkedIn public publication state is not proven")
        distribution = data.get("distribution")
        if (
            not isinstance(distribution, dict)
            or distribution.get("feedDistribution") != "MAIN_FEED"
        ):
            raise ReadbackError("LinkedIn main-feed distribution is not proven")
        permalink = str(data.get("permalink") or "")
        if not permalink.startswith("https://www.linkedin.com/"):
            page_key = (
                self.binding.config.get("public_slug") or self.binding.config["organization_id"]
            )
            permalink = f"https://www.linkedin.com/company/{page_key}/posts/"
        return AdapterResult(
            external_id=external_id,
            public_url=permalink,
            admin_url=(
                "https://www.linkedin.com/company/"
                f"{self.binding.config['organization_id']}/admin/page-posts/published/"
            ),
            content_hash=job.content_hash,
            canonical_url=job.canonical_url,
            readback=data,
            published_at=datetime.now(UTC),
        )

    def publish(self, job: PublicationJobIn, key: str) -> AdapterResult:
        self.preflight(job)
        response = self.client.request(
            self.channel,
            "POST",
            self._url("rest/posts"),
            headers=self._headers(),
            json_body=self._post_payload(job),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-linkedin-publish",
            max_attempts=1,
        )
        external_id = str(response.headers.get("x-restli-id") or "")
        if not external_id.startswith(("urn:li:share:", "urn:li:ugcPost:")):
            raise AdapterError("LinkedIn publish did not return a valid post URN")
        return self._readback(job, external_id)

    def rollback(self, job: PublicationJobIn, result: AdapterResult, reason: str) -> dict[str, Any]:
        self.client.request(
            self.channel,
            "DELETE",
            self._url(f"rest/posts/{quote(result.external_id, safe='')}"),
            headers=self._headers(method="DELETE"),
            correlation_id=job.correlation_id,
            request_id=f"{job.job_id}-linkedin-rollback",
            max_attempts=3,
        )
        try:
            self._readback(job, result.external_id)
        except PublishingHttpError as exc:
            if exc.status != 404:
                raise
        else:
            raise ReadbackError("LinkedIn rollback readback still finds post")
        return {
            "rollback_id": f"RB-LINKEDIN-{result.external_id}",
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
        return NIMAdapter(binding, client)
    if binding.channel == "wordpress":
        return WordPressAdapter(binding, client)
    if binding.channel in {"facebook", "instagram"}:
        return MetaAdapter(binding, client, binding.channel)
    if binding.channel == "linkedin":
        return LinkedInAdapter(binding, client)
    if binding.channel in {"analytics", "crm"}:
        adapter = EventAdapter(binding, client)
        adapter.channel = binding.channel
        return adapter
    if binding.channel == "forum":
        return ForumDraftAdapter(binding, client)
    raise RegistryError(f"Unsupported channel adapter: {binding.channel}")
