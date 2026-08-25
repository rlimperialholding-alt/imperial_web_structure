from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.outbound_email_guard import brand_from_sender, require_plain_single_brand_email


class ArtifactPublisher(Protocol):
    def publish_version(self, role: str, process_key: str, version: int, files: list[Path]) -> dict[str, str]: ...


class ApprovalNotifier(Protocol):
    def notify(self, *, process_key: str, title: str, version: int, role: str, artifact_links: dict[str, str], checklist_template_id: str | None = None) -> str: ...


@dataclass
class DirectusProcessSourceAdapter:
    base_url: str
    token: str
    collection: str = "process_catalog"

    def fetch(self, process_key: str) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/items/{self.collection}"
        params = {"filter[process_key][_eq]": process_key, "limit": 1}
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = httpx.get(url, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        rows = response.json().get("data", [])
        if not rows:
            raise KeyError(process_key)
        return rows[0]


@dataclass
class GoogleDrivePublisher:
    service_account_file: str
    root_folder_id: str

    REVIEW_ROOT = "00_JÓVÁHAGYÁSRA_VÁR"
    APPROVED_ROOT = "01_ÉRVÉNYES"
    REVIEW_ARCHIVE_ROOT = "99_JÓVÁHAGYÁSI_ARCHÍVUM"

    def _service(self):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = service_account.Credentials.from_service_account_file(
            self.service_account_file, scopes=scopes
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    @staticmethod
    def _escape_query(value: str) -> str:
        return value.replace("'", "\\'")

    def _find_folder(self, service, name: str, parent_id: str) -> str | None:
        safe = self._escape_query(name)
        query = (
            f"name='{safe}' and "
            "mimeType='application/vnd.google-apps.folder' and "
            f"'{parent_id}' in parents and trashed=false"
        )
        result = service.files().list(
            q=query, fields="files(id,name)", pageSize=10
        ).execute()
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def _ensure_folder(self, service, name: str, parent_id: str) -> str:
        existing = self._find_folder(service, name, parent_id)
        if existing:
            return existing
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        return service.files().create(body=metadata, fields="id").execute()["id"]

    def _ensure_path(self, service, parts: list[str]) -> str:
        parent = self.root_folder_id
        for part in parts:
            parent = self._ensure_folder(service, part, parent)
        return parent

    def _upload_files(self, service, folder_id: str, files: list[Path]) -> dict[str, str]:
        from googleapiclient.http import MediaFileUpload

        links: dict[str, str] = {}
        for path in files:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
            safe_name = self._escape_query(path.name)
            existing = service.files().list(
                q=f"name='{safe_name}' and '{folder_id}' in parents and trashed=false",
                fields="files(id,webViewLink)",
                pageSize=10,
            ).execute().get("files", [])
            if existing:
                created = service.files().update(
                    fileId=existing[0]["id"],
                    media_body=media,
                    fields="id,webViewLink",
                ).execute()
            else:
                created = service.files().create(
                    body={"name": path.name, "parents": [folder_id]},
                    media_body=media,
                    fields="id,webViewLink",
                ).execute()
            links[path.name] = created.get("webViewLink", created["id"])
        return links

    def publish_draft(
        self, role: str, process_key: str, version: int, files: list[Path]
    ) -> dict[str, str]:
        service = self._service()
        folder = self._ensure_path(
            service, [self.REVIEW_ROOT, role, process_key, f"v{version:03d}"]
        )
        return self._upload_files(service, folder, files)

    def publish_version(
        self, role: str, process_key: str, version: int, files: list[Path]
    ) -> dict[str, str]:
        service = self._service()
        folder = self._ensure_path(
            service, [self.APPROVED_ROOT, role, process_key, f"v{version:03d}"]
        )
        return self._upload_files(service, folder, files)

    def archive_draft(self, role: str, process_key: str, version: int) -> None:
        service = self._service()
        review_root = self._find_folder(service, self.REVIEW_ROOT, self.root_folder_id)
        if not review_root:
            return
        role_id = self._find_folder(service, role, review_root)
        if not role_id:
            return
        process_id = self._find_folder(service, process_key, role_id)
        if not process_id:
            return
        version_name = f"v{version:03d}"
        version_id = self._find_folder(service, version_name, process_id)
        if not version_id:
            return
        archive_process = self._ensure_path(
            service, [self.REVIEW_ARCHIVE_ROOT, role, process_key]
        )
        service.files().update(
            fileId=version_id,
            addParents=archive_process,
            removeParents=process_id,
            body={"name": f"{version_name}_JÓVÁHAGYVA"},
            fields="id,parents",
        ).execute()


@dataclass
class GmailApprovalNotifier:
    service_account_file: str
    delegated_user: str
    approver_email: str

    def notify(self, *, process_key: str, title: str, version: int, role: str, artifact_links: dict[str, str], checklist_template_id: str | None = None) -> str:
        import base64
        from email.message import EmailMessage

        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        scopes = ["https://www.googleapis.com/auth/gmail.send"]
        creds = service_account.Credentials.from_service_account_file(self.service_account_file, scopes=scopes).with_subject(self.delegated_user)
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        msg = EmailMessage()
        msg["To"] = self.approver_email
        msg["From"] = self.delegated_user
        subject, body = build_approval_email(
            sender_email=self.delegated_user,
            title=title,
            version=version,
            artifact_links=artifact_links,
        )
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent["id"]


def build_approval_email(
    *,
    sender_email: str,
    title: str,
    version: int,
    artifact_links: dict[str, str],
) -> tuple[str, str]:
    _, identity = brand_from_sender(sender_email)
    subject = "Új anyag jóváhagyása"
    links = "\n".join(
        f"- Fájl {index}: {url}"
        for index, url in enumerate(artifact_links.values(), start=1)
    ) or "- A fájlok a jóváhagyásra váró mappában találhatók."
    body = (
        f"Azért írunk, mert elkészült ez az anyag: {title}.\n"
        "Ez segít, hogy mindenki ugyanazt a jóváhagyott leírást használja.\n"
        f"Változat: {version}.\n\n"
        f"A fájlok:\n{links}\n\n"
        "Kérjük, nézze át, majd válaszoljon, hogy jóváhagyja-e.\n\n"
        f"{identity.name}"
    )
    require_plain_single_brand_email(
        sender_email=sender_email,
        subject=subject,
        body=body,
    )
    return subject, body


class NullNotifier:
    def notify(self, **kwargs) -> str:
        return "notifier-disabled"

@dataclass
class DirectusOperationalCatalogAdapter:
    base_url: str
    token: str
    process_collection: str = "process_catalog"
    checklist_collection: str = "checklist_templates"

    def _list(self, collection: str, status: str | None = None) -> list[dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}/items/{collection}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        params: dict[str, Any] = {"limit": -1}
        if status:
            params["filter[status][_eq]"] = status
        response = httpx.get(url, params=params, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json().get("data", [])

    @staticmethod
    def _clean_process(row: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "process_key",
            "title",
            "trigger",
            "inputs",
            "steps",
            "outputs",
            "stop_conditions",
            "completion_conditions",
            "source_role",
            "policy_refs",
            "source_updated_at",
            "family",
            "gate_id",
            "checklist_template_id",
            "object_type",
            "participant_roles",
            "external_participants",
            "approval_role",
            "checklist_required",
            "source_version",
            "metadata",
        }
        return {key: row.get(key) for key in allowed if key in row}

    @staticmethod
    def _clean_template(row: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "template_id",
            "process_key",
            "title",
            "family",
            "primary_role",
            "participant_roles",
            "external_participants",
            "when_to_use",
            "gate_id",
            "object_type",
            "items",
            "stop_conditions",
            "required_evidence",
            "closer_approver",
            "answer_mode",
            "version",
            "status",
            "source_url",
            "checksum",
            "approved_at",
            "approved_by",
            "metadata",
        }
        return {key: row.get(key) for key in allowed if key in row}

    def fetch_catalog(self) -> dict[str, Any]:
        processes = [self._clean_process(row) for row in self._list(self.process_collection, "active")]
        templates = [self._clean_template(row) for row in self._list(self.checklist_collection)]
        return {
            "catalog_id": "DIRECTUS-OPERATIONAL-CATALOG",
            "catalog_version": "live",
            "processes": processes,
            "checklist_templates": templates,
        }
