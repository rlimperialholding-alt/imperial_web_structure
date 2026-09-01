# ruff: noqa: E501 -- SVG fragments are intentionally kept as one auditable template.
from __future__ import annotations

import html
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import HouseDesignRenderRevision, HouseDesignRevision, HouseDesignSession
from .house_designer import ActorScope, HouseDesignerError
from .house_designer_geometry import canonical_sha256


def create_sandbox_render(
    db: Session,
    *,
    session_id: str,
    actor: ActorScope,
    prompt: str,
    idempotency_key: str | None = None,
    expected_parent_render_id: str | None = None,
) -> dict[str, Any]:
    session = _locked_readable_session(db, session_id, actor)
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == session.current_revision_id
        )
    )
    if revision is None:
        raise HouseDesignerError(
            "current_revision_missing", "A terv aktuális verziója nem elérhető.", status_code=409
        )
    clean_prompt = " ".join(prompt.strip().split())
    if not clean_prompt:
        clean_prompt = "Modern, időtálló családi ház természetes anyaghasználattal."
    if len(clean_prompt) > 1_000:
        raise HouseDesignerError("render_prompt_too_long", "A látványutasítás túl hosszú.")
    if idempotency_key:
        replay = db.scalar(
            select(HouseDesignRenderRevision).where(
                HouseDesignRenderRevision.provider_job_id == f"api:{idempotency_key}"
            )
        )
        if replay:
            if (
                replay.session_id == session_id
                and replay.design_revision_id == revision.revision_id
                and replay.prompt == clean_prompt
            ):
                return _render_result(replay)
            raise HouseDesignerError(
                "idempotency_collision",
                "A műveletazonosító más látványkéréshez tartozik.",
                status_code=409,
            )
    revision_no = (
        db.scalar(
            select(func.max(HouseDesignRenderRevision.revision_no)).where(
                HouseDesignRenderRevision.session_id == session_id
            )
        )
        or 0
    ) + 1
    parent = db.scalar(
        select(HouseDesignRenderRevision)
        .where(HouseDesignRenderRevision.session_id == session_id)
        .order_by(desc(HouseDesignRenderRevision.revision_no))
    )
    if expected_parent_render_id and (
        parent is None or parent.render_id != expected_parent_render_id
    ):
        raise HouseDesignerError(
            "stale_render_revision",
            "A látványterv időközben újabb verziót kapott; frissítés szükséges.",
            status_code=409,
        )
    geometry = json.loads(revision.geometry_json)
    render = HouseDesignRenderRevision(
        render_id=f"HDV-{uuid4().hex}",
        session_id=session_id,
        design_revision_id=revision.revision_id,
        revision_no=revision_no,
        parent_render_id=parent.render_id if parent else None,
        geometry_lock_sha256=canonical_sha256(geometry),
        prompt=clean_prompt,
        provider="sandbox_svg_v1",
        provider_job_id=f"api:{idempotency_key}" if idempotency_key else None,
        qa_json=json.dumps(
            {
                "geometryLockVerified": True,
                "watermarked": True,
                "photorealistic": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        status="ready",
        non_production=True,
        created_by=actor.subject_id,
    )
    db.add(render)
    audit(
        db,
        actor=actor.subject_id,
        action="house_designer.sandbox_render.create",
        entity_type="HouseDesignSession",
        entity_id=session_id,
        after={
            "render_id": render.render_id,
            "design_revision_id": revision.revision_id,
            "revision_no": revision_no,
            "non_production": True,
        },
    )
    db.commit()
    return _render_result(render)


def revise_sandbox_render(
    db: Session,
    *,
    render_id: str,
    actor: ActorScope,
    prompt: str,
    idempotency_key: str,
) -> dict[str, Any]:
    parent = db.scalar(
        select(HouseDesignRenderRevision).where(HouseDesignRenderRevision.render_id == render_id)
    )
    if parent is None:
        raise HouseDesignerError("render_not_found", "A látvány nem található.", status_code=404)
    session = _readable_session(db, parent.session_id, actor)
    if session.current_revision_id != parent.design_revision_id:
        raise HouseDesignerError(
            "stale_design_revision",
            "A látvány nem a jelenlegi alaprajzhoz tartozik.",
            status_code=409,
        )
    return create_sandbox_render(
        db,
        session_id=parent.session_id,
        actor=actor,
        prompt=prompt,
        idempotency_key=idempotency_key,
        expected_parent_render_id=render_id,
    )


def list_current_renders(
    db: Session, *, session_id: str, revision_id: str, actor: ActorScope
) -> list[dict[str, Any]]:
    session = _readable_session(db, session_id, actor)
    if session.current_revision_id != revision_id:
        return []
    rows = db.scalars(
        select(HouseDesignRenderRevision)
        .where(
            HouseDesignRenderRevision.session_id == session_id,
            HouseDesignRenderRevision.design_revision_id == revision_id,
        )
        .order_by(desc(HouseDesignRenderRevision.revision_no))
        .limit(20)
    ).all()
    return [_render_result(row) for row in rows]


def sandbox_render_svg(db: Session, *, render_id: str, actor: ActorScope) -> str:
    render = db.scalar(
        select(HouseDesignRenderRevision).where(HouseDesignRenderRevision.render_id == render_id)
    )
    if render is None:
        raise HouseDesignerError("render_not_found", "A látvány nem található.", status_code=404)
    _readable_session(db, render.session_id, actor)
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == render.design_revision_id
        )
    )
    if revision is None:
        raise HouseDesignerError("render_not_found", "A látvány nem található.", status_code=404)
    geometry = json.loads(revision.geometry_json)
    if canonical_sha256(geometry) != render.geometry_lock_sha256:
        raise HouseDesignerError(
            "render_geometry_mismatch", "A látvány geometriakapcsolata sérült.", status_code=409
        )
    configuration = json.loads(revision.configuration_json)
    return _svg(geometry, configuration, render.prompt, render.revision_no)


def _readable_session(db: Session, session_id: str, actor: ActorScope) -> HouseDesignSession:
    session = db.scalar(
        select(HouseDesignSession).where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == actor.tenant_id,
        )
    )
    if (
        session is None
        or session.brand_id not in actor.brand_ids
        or not actor.can_read(session.owner_subject_id, session.project_id)
    ):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    return session


def _locked_readable_session(db: Session, session_id: str, actor: ActorScope) -> HouseDesignSession:
    session = db.scalar(
        select(HouseDesignSession)
        .where(
            HouseDesignSession.session_id == session_id,
            HouseDesignSession.tenant_id == actor.tenant_id,
        )
        .with_for_update()
    )
    if (
        session is None
        or session.brand_id not in actor.brand_ids
        or not actor.can_read(session.owner_subject_id, session.project_id)
    ):
        raise HouseDesignerError("session_not_found", "A házterv nem található.", status_code=404)
    if session.status in {"SUBMITTED", "ARCHIVED", "CANCELLED"}:
        raise HouseDesignerError(
            "session_not_editable",
            "A házterv ebben az állapotban nem módosítható.",
            status_code=409,
        )
    return session


def _render_result(row: HouseDesignRenderRevision) -> dict[str, Any]:
    return {
        "renderId": row.render_id,
        "sessionId": row.session_id,
        "designRevisionId": row.design_revision_id,
        "revisionNo": row.revision_no,
        "parentRenderId": row.parent_render_id,
        "prompt": row.prompt,
        "status": row.status,
        "nonProduction": row.non_production,
        "createdAt": row.created_at,
    }


def _svg(
    geometry: dict[str, Any], configuration: dict[str, Any], prompt: str, revision_no: int
) -> str:
    level_count = max(1, len(geometry.get("levels") or []))
    roof = (geometry.get("levels") or [{}])[-1].get("roof") or {}
    roof_type = str(roof.get("type") or configuration.get("roofType") or "gable")
    technology = str(configuration.get("constructionTechnology") or "masonry")
    palette = {
        "timber-frame": ("#d8c3a5", "#765b3d"),
        "masonry": ("#e8e2d8", "#504b47"),
        "reinforced-concrete": ("#d9dde1", "#38434c"),
    }
    wall, accent = palette.get(technology, palette["masonry"])
    base_y = 365
    floor_height = min(92, 245 // level_count)
    house_top = base_y - floor_height * level_count
    floors = []
    windows = []
    for index in range(level_count):
        y = base_y - floor_height * (index + 1)
        floors.append(
            f'<rect x="170" y="{y}" width="560" height="{floor_height}" fill="{wall}" '
            f'stroke="{accent}" stroke-width="3"/>'
        )
        for x in (240, 390, 540, 650):
            windows.append(
                f'<rect x="{x}" y="{y + 20}" width="58" height="{max(28, floor_height - 38)}" '
                'rx="3" fill="#b9d8e8" stroke="#ffffff" stroke-width="5"/>'
            )
    if roof_type == "flat":
        roof_svg = f'<rect x="155" y="{house_top - 14}" width="590" height="18" fill="{accent}"/>'
    else:
        roof_svg = (
            f'<polygon points="145,{house_top} 450,{house_top - 125} 755,{house_top}" '
            f'fill="{accent}" stroke="#2d2926" stroke-width="4"/>'
        )
    safe_prompt = html.escape(prompt)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 520" role="img" aria-label="Teszt házlátvány">
<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#cde9fb"/><stop offset="1" stop-color="#f8fbfd"/></linearGradient></defs>
<rect width="900" height="520" fill="url(#sky)"/><circle cx="770" cy="80" r="42" fill="#f8d875"/><path d="M0 385 Q220 340 460 385 T900 375 V520 H0Z" fill="#88ad70"/>
{"".join(floors)}{"".join(windows)}{roof_svg}<rect x="425" y="300" width="58" height="65" fill="#684a37"/>
<text x="24" y="32" font-family="Arial,sans-serif" font-size="17" font-weight="700" fill="#8c1d18">TESZTLÁTVÁNY · NEM ÉPÍTÉSZETI DOKUMENTUM</text>
<rect x="20" y="438" width="860" height="58" rx="10" fill="#ffffff" fill-opacity=".88"/><text x="38" y="463" font-family="Arial,sans-serif" font-size="15" fill="#23384d">v{revision_no} · {safe_prompt[:105]}</text><text x="38" y="484" font-family="Arial,sans-serif" font-size="13" fill="#5c6773">Sandbox SVG · geometriazáras, nem fotórealisztikus HouseVision-előnézet</text>
</svg>"""
