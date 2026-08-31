from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    ContentAssetRecord,
    OutboxMessage,
    PublicationBundleRecord,
    WebsitePublicationIncident,
    WebsiteRelease,
    WebsiteReleaseTarget,
    WebsiteRouteState,
    WebsiteSite,
)
from ..schemas import WebsiteDeliveryReceiptIn, WebsiteReleaseIn, WebsiteSiteIn, WebsiteSmokeTestIn


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _sha(value: str) -> str:
    value = value.strip().lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("Érvényes SHA-256 lenyomat szükséges.")
    return value


def _public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A webhely és adapter kizárólag publikus http/https URL lehet.")
    if parsed.username or parsed.password:
        raise ValueError("Felhasználónevet vagy jelszót tartalmazó URL tiltott; titokhivatkozás szükséges.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Az URL portja érvénytelen.") from exc
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise ValueError("Belső, localhost vagy metadata cím tiltott.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("A domain nem oldható fel biztonságosan.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Privát, loopback, link-local, reserved vagy multicast cím tiltott.")
    return value.rstrip("/")


def _matches_canonical(published_url: str, canonical_url: str) -> bool:
    published = urlparse(_public_url(published_url))
    canonical = urlparse(_public_url(canonical_url))
    published_port = published.port or (443 if published.scheme == "https" else 80)
    canonical_port = canonical.port or (443 if canonical.scheme == "https" else 80)
    return (
        published.scheme == canonical.scheme
        and published.hostname == canonical.hostname
        and published_port == canonical_port
        and published.path.rstrip("/") == canonical.path.rstrip("/")
    )


def _release(db: Session, release_id: str) -> WebsiteRelease:
    row = db.scalar(select(WebsiteRelease).where(WebsiteRelease.release_id == release_id))
    if not row:
        raise KeyError(release_id)
    return row


def _target(db: Session, target_id: str) -> WebsiteReleaseTarget:
    row = db.scalar(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.target_id == target_id))
    if not row:
        raise KeyError(target_id)
    return row


def register_site(db: Session, data: WebsiteSiteIn, actor: str, actor_role: str) -> WebsiteSite:
    if actor_role not in {"owner", "managing-director", "marketing", "platform-admin"}:
        raise PermissionError("Webhelyregisztrációra nincs jogosultság.")
    base_url = _public_url(data.base_url)
    adapter_endpoint = _public_url(data.adapter_endpoint)
    row = WebsiteSite(site_id=_id("SITE"), brand_id=data.brand_id, name=data.name, base_url=base_url, adapter_endpoint=adapter_endpoint, credential_ref=data.credential_ref, active=True, kill_switch=False, created_by=actor)
    db.add(row)
    audit(db, actor=actor, action="website.site.register", entity_type="website_site", entity_id=row.site_id, after={"brand_id": row.brand_id, "base_url": base_url, "adapter_endpoint": adapter_endpoint})
    db.commit(); db.refresh(row); return row


def set_kill_switch(db: Session, site_id: str, enabled: bool, reason: str, actor: str, actor_role: str) -> WebsiteSite:
    if actor_role not in {"owner", "managing-director", "platform-admin"}:
        raise PermissionError("Kill switch módosítására nincs jogosultság.")
    if len(reason.strip()) < 10:
        raise ValueError("Részletes indoklás szükséges.")
    site = db.scalar(select(WebsiteSite).where(WebsiteSite.site_id == site_id))
    if not site: raise KeyError(site_id)
    site.kill_switch = enabled; site.kill_switch_reason = reason if enabled else None
    audit(db, actor=actor, action="website.site.kill_switch", entity_type="website_site", entity_id=site_id, after={"enabled": enabled, "reason": reason})
    db.commit(); db.refresh(site); return site


def create_release(db: Session, data: WebsiteReleaseIn, actor: str, actor_role: str) -> WebsiteRelease:
    if actor_role not in {"owner", "managing-director", "marketing", "platform-admin"}:
        raise PermissionError("Webrelease létrehozására nincs jogosultság.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == data.asset_id))
    if not asset: raise KeyError(data.asset_id)
    if asset.state not in {"LIVE_QA", "PUBLISHED"} or not asset.publication_proof_id or not asset.active_bundle_id:
        raise ValueError("Csak publikációs bizonyítékkal rendelkező LIVE_QA vagy PUBLISHED asset adható webhelyre.")
    bundle = db.get(PublicationBundleRecord, asset.active_bundle_id)
    if not bundle or bundle.status != "APPROVED" or bundle.content_hash != asset.content_hash:
        raise ValueError("Az aktív, jóváhagyott PublicationBundle hiányzik vagy elavult.")
    keys = {(item.site_id, item.route_path, item.locale) for item in data.targets}
    if len(keys) != len(data.targets): raise ValueError("A release célhelyei nem lehetnek duplikáltak.")
    sites = {row.site_id: row for row in db.scalars(select(WebsiteSite).where(WebsiteSite.site_id.in_({item.site_id for item in data.targets}))).all()}
    if len(sites) != len({item.site_id for item in data.targets}): raise KeyError("Ismeretlen webhely.")
    for target in data.targets:
        site = sites[target.site_id]
        if not site.active or site.kill_switch: raise ValueError(f"A webhely inaktív vagy kill switch alatt áll: {site.site_id}")
        if site.brand_id != asset.brand_id: raise ValueError("A tartalom márkája és a webhely márkája eltér.")
        if not target.route_path.startswith("/") or ".." in target.route_path: raise ValueError("A route abszolút, biztonságos webhelyútvonal legyen.")
    version = 1 + (db.scalar(
        select(func.count()).select_from(WebsiteRelease).where(WebsiteRelease.asset_id == data.asset_id)
    ) or 0)
    manifest = {"asset_id": asset.asset_id, "content_version": asset.content_version, "content_sha256": asset.content_hash, "bundle_id": bundle.bundle_id, "bundle_sha256": bundle.bundle_hash, "publication_proof_id": asset.publication_proof_id, "targets": [item.model_dump() for item in data.targets]}
    row = WebsiteRelease(release_id=_id("WEBREL"), asset_id=asset.asset_id, version=version, content_version=asset.content_version, content_sha256=asset.content_hash, publication_bundle_id=bundle.bundle_id, publication_proof_id=asset.publication_proof_id, release_manifest_sha256=_hash(manifest), target_count=len(data.targets), status="ready", created_by=actor)
    db.add(row)
    for item in data.targets:
        site = sites[item.site_id]
        payload = {"release_id": row.release_id, "site_id": site.site_id, "route_path": item.route_path, "locale": item.locale, "content_sha256": asset.content_hash, "bundle_sha256": bundle.bundle_hash}
        db.add(WebsiteReleaseTarget(target_id=_id("WEBTGT"), release_id=row.release_id, site_id=site.site_id, route_path=item.route_path, locale=item.locale, canonical_url=urljoin(site.base_url + "/", item.route_path.lstrip("/")), payload_sha256=_hash(payload), status="pending"))
    audit(db, actor=actor, action="website.release.create", entity_type="website_release", entity_id=row.release_id, after={"asset_id": asset.asset_id, "version": version, "manifest_sha256": row.release_manifest_sha256, "targets": len(data.targets)})
    db.commit(); db.refresh(row); return row


def dispatch_release(db: Session, release_id: str, actor: str, actor_role: str) -> WebsiteRelease:
    if actor_role not in {"owner", "managing-director", "marketing", "platform-admin"}: raise PermissionError("Webrelease indítására nincs jogosultság.")
    release = _release(db, release_id)
    if release.status != "ready": raise ValueError("Csak ready release indítható.")
    asset = db.scalar(select(ContentAssetRecord).where(ContentAssetRecord.asset_id == release.asset_id))
    bundle = db.get(PublicationBundleRecord, release.publication_bundle_id)
    if (
        not asset
        or asset.state not in {"LIVE_QA", "PUBLISHED"}
        or asset.content_hash != release.content_sha256
        or asset.active_bundle_id != release.publication_bundle_id
        or asset.publication_proof_id != release.publication_proof_id
        or not bundle
        or bundle.status != "APPROVED"
        or bundle.content_hash != release.content_sha256
    ):
        raise ValueError("A ContentAsset, PublicationBundle vagy PublicationProof a release létrehozása óta megváltozott.")
    targets = db.scalars(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.release_id == release_id)).all()
    for target in targets:
        site = db.scalar(select(WebsiteSite).where(WebsiteSite.site_id == target.site_id))
        if not site or not site.active or site.kill_switch: raise ValueError("Legalább egy célwebhely inaktív vagy kill switch alatt áll.")
        payload = {"action": "publish", "idempotency_key": target.target_id, "release_id": release_id, "target_id": target.target_id, "site_id": target.site_id, "route_path": target.route_path, "locale": target.locale, "canonical_url": target.canonical_url, "content_sha256": release.content_sha256, "payload_sha256": target.payload_sha256, "publication_bundle_id": release.publication_bundle_id, "publication_proof_id": release.publication_proof_id, "content": json.loads(asset.content_json)}
        db.add(OutboxMessage(message_id=_id("MSG-WEB"), destination_module=f"website-adapter:{site.site_id}", endpoint=site.adapter_endpoint, payload_json=_json(payload), status="pending", max_retries=5, next_attempt_at=utcnow()))
        target.status = "dispatched"; target.attempt_count += 1
    release.status = "deploying"; release.dispatched_at = utcnow()
    audit(db, actor=actor, action="website.release.dispatch", entity_type="website_release", entity_id=release_id, after={"targets": len(targets)})
    db.commit(); db.refresh(release); return release


def _queue_rollback(db: Session, release: WebsiteRelease, failed_target_id: str | None, reason: str, actor: str) -> None:
    targets = db.scalars(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.release_id == release.release_id)).all()
    queued = 0
    for target in targets:
        if target.status not in {"dispatched", "delivered", "smoke_pass", "smoke_failed", "live"}: continue
        route = db.scalar(select(WebsiteRouteState).where(WebsiteRouteState.site_id == target.site_id, WebsiteRouteState.route_path == target.route_path, WebsiteRouteState.locale == target.locale))
        previous = _target(db, route.current_target_id) if route else None
        site = db.scalar(select(WebsiteSite).where(WebsiteSite.site_id == target.site_id))
        if not site:
            raise ValueError(f"A rollback célwebhelye hiányzik: {target.site_id}")
        action = "restore" if previous and previous.external_version_id else "unpublish"
        db.add(OutboxMessage(message_id=_id("MSG-WEB"), destination_module=f"website-adapter:{target.site_id}", endpoint=site.adapter_endpoint, payload_json=_json({"action": action, "failed_release_id": release.release_id, "target_id": target.target_id, "route_path": target.route_path, "restore_external_version_id": previous.external_version_id if previous else None, "reason": reason}), status="pending", max_retries=5, next_attempt_at=utcnow()))
        target.status = "rollback_queued"; queued += 1
    incident = WebsitePublicationIncident(incident_id=_id("WEBINC"), release_id=release.release_id, target_id=failed_target_id, severity="critical", incident_type="delivery_or_smoke_failure", description=reason, rollback_action="restore_previous_or_unpublish", status="open", created_by=actor)
    db.add(incident); release.status = "failed"; release.failure_reason = reason; release.auto_rollback_status = "queued" if queued else "not_required"


def record_delivery_receipt(db: Session, data: WebsiteDeliveryReceiptIn, actor: str, actor_role: str) -> WebsiteReleaseTarget:
    if actor_role not in {"owner", "managing-director", "marketing", "platform-admin", "adapter"}:
        raise PermissionError("CMS delivery receipt rögzítésére nincs jogosultság.")
    target = _target(db, data.target_id)
    release = _release(db, target.release_id)
    if data.idempotency_key != target.target_id: raise ValueError("Az idempotency key nem a célrekordhoz tartozik.")
    if target.status == "delivered" and data.success and target.external_version_id == data.external_version_id: return target
    if target.status != "dispatched": raise ValueError("Delivery receipt csak dispatched célhoz fogadható.")
    if not data.success:
        target.failure_reason = data.error_message or "Ismeretlen adapterhiba"
        _queue_rollback(db, release, target.target_id, target.failure_reason, actor)
    else:
        if not data.external_version_id or not data.published_url or not data.rendered_content_sha256: raise ValueError("Sikeres receiptből hiányzik a külső verzió, URL vagy visszaolvasott hash.")
        if _sha(data.rendered_content_sha256) != release.content_sha256: raise ValueError("A visszaolvasott tartalomhash eltér a jóváhagyott verziótól.")
        if not _matches_canonical(data.published_url, target.canonical_url): raise ValueError("A publikált URL nem a kijelölt canonical célhoz tartozik.")
        target.external_version_id = data.external_version_id; target.published_url = data.published_url; target.rendered_content_sha256 = data.rendered_content_sha256; target.receipt_at = utcnow(); target.status = "delivered"
    audit(db, actor=actor, action="website.delivery.receipt", entity_type="website_release_target", entity_id=target.target_id, after={"success": data.success, "status": target.status, "external_version_id": target.external_version_id})
    db.commit(); db.refresh(target); return target


def _activate_if_complete(db: Session, release: WebsiteRelease, actor: str) -> None:
    targets = db.scalars(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.release_id == release.release_id)).all()
    if not targets or any(target.status != "smoke_pass" for target in targets): return
    for target in targets:
        route = db.scalar(select(WebsiteRouteState).where(WebsiteRouteState.site_id == target.site_id, WebsiteRouteState.route_path == target.route_path, WebsiteRouteState.locale == target.locale))
        target.previous_target_id = route.current_target_id if route else None
        if route:
            previous = _target(db, route.current_target_id)
            if previous.status == "live":
                previous.status = "superseded"
        target.status = "live"
        if route:
            route.current_release_id = release.release_id; route.current_target_id = target.target_id
        else:
            db.add(WebsiteRouteState(route_state_id=_id("WEBROUTE"), site_id=target.site_id, route_path=target.route_path, locale=target.locale, current_release_id=release.release_id, current_target_id=target.target_id))
    release.status = "live"; release.activated_at = utcnow(); release.auto_rollback_status = "not_required"
    for destination in ("analytics", "crm", "control-center"):
        db.add(OutboxMessage(message_id=_id("MSG-WEB"), destination_module=destination, endpoint="/website/releases", payload_json=_json({"event": "CONTENT_PUBLISHED", "release_id": release.release_id, "asset_id": release.asset_id, "manifest_sha256": release.release_manifest_sha256}), status="pending", max_retries=5, next_attempt_at=utcnow()))
    audit(db, actor=actor, action="website.release.activate", entity_type="website_release", entity_id=release.release_id, after={"status": "live", "targets": len(targets)})


def record_smoke_test(db: Session, target_id: str, data: WebsiteSmokeTestIn, actor: str, actor_role: str) -> WebsiteReleaseTarget:
    if actor_role not in {"owner", "managing-director", "marketing", "platform-admin", "smoke-runner"}:
        raise PermissionError("Publikációs smoke teszt rögzítésére nincs jogosultság.")
    target = _target(db, target_id); release = _release(db, target.release_id)
    if target.status != "delivered": raise ValueError("Smoke teszt csak delivered célhoz rögzíthető.")
    gates = {"http": 200 <= data.http_status < 300, "rendered_content": _sha(data.rendered_content_sha256) == release.content_sha256, "link": data.link_pass, "form": data.form_pass, "schema": data.schema_pass, "canonical": data.canonical_pass, "accessibility": data.accessibility_pass, "analytics": data.analytics_pass, "crm": data.crm_pass, "privacy": data.privacy_pass, "mobile_render": data.mobile_render_pass}
    passed = all(gates.values())
    target.smoke_http_status = data.http_status; target.smoke_json = _json(gates); target.smoke_at = utcnow(); target.status = "smoke_pass" if passed else "smoke_failed"
    if not passed:
        target.failure_reason = "Hibás smoke kapuk: " + ", ".join(key for key, value in gates.items() if not value)
        _queue_rollback(db, release, target_id, target.failure_reason, actor)
    else:
        _activate_if_complete(db, release, actor)
    audit(db, actor=actor, action="website.smoke.record", entity_type="website_release_target", entity_id=target_id, after={"passed": passed, "gates": gates, "release_status": release.status})
    db.commit(); db.refresh(target); return target


def rollback_release(db: Session, release_id: str, reason: str, actor: str, actor_role: str) -> WebsiteRelease:
    if actor_role not in {"owner", "managing-director", "marketing", "platform-admin"}: raise PermissionError("Webrelease rollbackra nincs jogosultság.")
    if len(reason.strip()) < 10: raise ValueError("Részletes rollback-indok szükséges.")
    release = _release(db, release_id)
    if release.status != "live": raise ValueError("Csak élő release állítható vissza.")
    targets = db.scalars(select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.release_id == release_id, WebsiteReleaseTarget.status == "live")).all()
    for target in targets:
        route = db.scalar(select(WebsiteRouteState).where(WebsiteRouteState.current_target_id == target.target_id))
        previous = _target(db, target.previous_target_id) if target.previous_target_id else None
        site = db.scalar(select(WebsiteSite).where(WebsiteSite.site_id == target.site_id))
        if not site:
            raise ValueError(f"A rollback célwebhelye hiányzik: {target.site_id}")
        action = "restore" if previous and previous.external_version_id else "unpublish"
        db.add(OutboxMessage(message_id=_id("MSG-WEB"), destination_module=f"website-adapter:{target.site_id}", endpoint=site.adapter_endpoint, payload_json=_json({"action": action, "release_id": release_id, "target_id": target.target_id, "restore_external_version_id": previous.external_version_id if previous else None, "reason": reason}), status="pending", max_retries=5, next_attempt_at=utcnow()))
        if route and previous:
            route.current_release_id = previous.release_id; route.current_target_id = previous.target_id
            previous.status = "live"
        elif route:
            db.delete(route)
        target.status = "rolled_back"
    release.status = "rolled_back"; release.auto_rollback_status = "manual_queued"; release.rolled_back_at = utcnow(); release.rolled_back_by = actor; release.failure_reason = reason
    db.add(WebsitePublicationIncident(incident_id=_id("WEBINC"), release_id=release_id, target_id=None, severity="high", incident_type="manual_rollback", description=reason, rollback_action="restore_previous_or_unpublish", status="resolved", created_by=actor, resolved_at=utcnow()))
    for destination in ("analytics", "crm", "control-center"):
        db.add(OutboxMessage(message_id=_id("MSG-WEB"), destination_module=destination, endpoint="/website/releases", payload_json=_json({"event": "CONTENT_ROLLED_BACK", "release_id": release_id, "asset_id": release.asset_id, "reason": reason}), status="pending", max_retries=5, next_attempt_at=utcnow()))
    audit(db, actor=actor, action="website.release.rollback", entity_type="website_release", entity_id=release_id, after={"reason": reason, "targets": len(targets)})
    db.commit(); db.refresh(release); return release


def workspace(db: Session) -> dict:
    sites = db.scalars(select(WebsiteSite).order_by(WebsiteSite.brand_id, WebsiteSite.name)).all()
    releases = db.scalars(select(WebsiteRelease).order_by(desc(WebsiteRelease.created_at))).all()
    targets = db.scalars(select(WebsiteReleaseTarget).order_by(desc(WebsiteReleaseTarget.created_at))).all()
    incidents = db.scalars(select(WebsitePublicationIncident).order_by(desc(WebsitePublicationIncident.created_at))).all()
    assets = db.scalars(select(ContentAssetRecord).where(ContentAssetRecord.state.in_(("LIVE_QA", "PUBLISHED"))).order_by(desc(ContentAssetRecord.updated_at))).all()
    return {"sites": sites, "releases": releases, "targets": targets, "incidents": incidents, "assets": assets, "routes": db.scalars(select(WebsiteRouteState).order_by(WebsiteRouteState.site_id, WebsiteRouteState.route_path)).all(), "metrics": {"sites": len(sites), "live_releases": sum(row.status == "live" for row in releases), "deploying": sum(row.status == "deploying" for row in releases), "failed": sum(row.status == "failed" for row in releases), "kill_switches": sum(row.kill_switch for row in sites), "open_incidents": sum(row.status == "open" for row in incidents)}}
