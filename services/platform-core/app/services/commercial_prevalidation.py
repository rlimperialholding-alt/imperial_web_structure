from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..copy_gate.models import ContentAsset, ExternalActionType, PrevalidatedSourceEvidence
from .pricing import WEB_PRICES_FILE, pricing_repository

BASE_DIR = Path(__file__).resolve().parents[2]
REGISTRY_FILE = BASE_DIR / "app" / "static" / "prevalidated-commercial-sources" / "manifest.json"

BRAND_ALIASES = {
    "imperial holding": "imperial",
    "imperial": "imperial",
    "danish fabrik": "danish-fabrik",
    "danish-fabrik": "danish-fabrik",
    "bautica": "bautica",
    "prefab": "prefab",
    "casa moderna": "casa-moderna",
    "casa-moderna": "casa-moderna",
    "baufreund": "baufreund",
    "timberhaus": "timberhaus",
}

PRICING_BRAND_NAMES = {
    "imperial": "imperial",
    "bautica": "bautica",
    "prefab": "prefab",
    "danish-fabrik": "danish fabrik",
    "baufreund": "baufreund",
}

GATE_BY_CATEGORY = {
    "legal": "GATE_2_LEGAL_POLICY",
    "commercial": "GATE_3_FINANCIAL_COMMERCIAL",
    "price": "GATE_3_FINANCIAL_COMMERCIAL",
    "technical": "GATE_4_TECHNICAL_FACTUAL",
    "typehouse": "GATE_4_TECHNICAL_FACTUAL",
    "floorplan": "GATE_4_TECHNICAL_FACTUAL",
}


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_brand_id(value: str) -> str:
    return BRAND_ALIASES.get(normalize(value), normalize(value).replace(" ", "-"))


@lru_cache(maxsize=1)
def load_prevalidated_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class CommercialPrevalidationResult:
    eligible: bool
    registry_version: str
    registry_sha256: str
    gate_coverage: dict[str, bool]
    verified_evidence_ids: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def _asset_text(asset: ContentAsset) -> str:
    return " ".join(
        [
            asset.title,
            asset.body,
            asset.cta,
            asset.slogan,
            *asset.factual_claims,
            *asset.price_mentions,
            *asset.deadline_mentions,
            *asset.condition_mentions,
        ]
    )


def _matches_declared_claim(asset: ContentAsset, evidence: PrevalidatedSourceEvidence) -> bool:
    claim = normalize(evidence.claim_text or "")
    if not claim or claim not in normalize(_asset_text(asset)):
        return False
    return True


def _validate_website_fragment(
    evidence: PrevalidatedSourceEvidence,
    *,
    brand_registry: dict[str, Any],
    registry_version: str,
    asset: ContentAsset,
) -> str | None:
    if evidence.source_version != registry_version:
        return f"{evidence.evidence_id}: a website snapshot verziója eltér."
    by_hash = {item["fragment_sha256"]: item for item in brand_registry.get("fragments", [])}
    expected = by_hash.get((evidence.source_fragment_sha256 or "").lower())
    if not expected:
        return f"{evidence.evidence_id}: a website-fragmentum nincs az elővalidált snapshotban."
    if expected["source_url"] != evidence.source_url:
        return f"{evidence.evidence_id}: a website forrás-URL eltér."
    normalized_fragment = normalize(evidence.source_fragment or "")
    if sha256_text(normalized_fragment) != expected["fragment_sha256"]:
        return f"{evidence.evidence_id}: a website-fragmentum hash-ellenőrzése sikertelen."
    if evidence.category not in expected["categories"]:
        return f"{evidence.evidence_id}: a forráskategória eltér."
    claim = normalize(evidence.claim_text or "")
    if claim not in normalized_fragment or not _matches_declared_claim(asset, evidence):
        return f"{evidence.evidence_id}: a közölt állítás nem a snapshot pontos részlete."
    return None


def _validate_website_visual(
    evidence: PrevalidatedSourceEvidence,
    *,
    brand_registry: dict[str, Any],
    registry_version: str,
    asset: ContentAsset,
) -> str | None:
    if evidence.source_version != registry_version:
        return f"{evidence.evidence_id}: a vizuális snapshot verziója eltér."
    by_reference = {
        item["reference_sha256"]: item for item in brand_registry.get("typehouse_assets", [])
    }
    expected = by_reference.get((evidence.visual_reference_sha256 or "").lower())
    if not expected:
        return f"{evidence.evidence_id}: a típusház/floorplan asset nincs a snapshotban."
    if expected["source_page"] != evidence.source_url:
        return f"{evidence.evidence_id}: a vizuális asset forrásoldala eltér."
    if expected["asset_url"] != evidence.visual_asset_url:
        return f"{evidence.evidence_id}: a vizuális asset URL-je eltér."
    if evidence.visual_asset_id not in asset.visual_asset_ids:
        return f"{evidence.evidence_id}: a bizonyíték nem az asset által használt vizuálra mutat."
    return None


def _validate_drive_price(
    evidence: PrevalidatedSourceEvidence,
    *,
    registry: dict[str, Any],
    brand_id: str,
    asset: ContentAsset,
) -> str | None:
    price_sources = {item["registry_id"]: item for item in registry.get("price_sources", [])}
    source = price_sources.get(evidence.source_ref)
    if not source:
        return f"{evidence.evidence_id}: ismeretlen Drive árforrás."
    if brand_id not in source["brands"]:
        return f"{evidence.evidence_id}: az árforrás nem ehhez a márkához tartozik."
    if evidence.source_version != source["source_version"]:
        return f"{evidence.evidence_id}: az árforrás verziója eltér."
    if (evidence.source_sha256 or "").lower() != source["sha256"]:
        return f"{evidence.evidence_id}: az árforrás hash-e eltér."
    if evidence.source_ref == "drive-web-prices-2026-07":
        if file_sha256(WEB_PRICES_FILE) != source["sha256"]:
            return f"{evidence.evidence_id}: a helyi kalkulációs forrás megváltozott."
    else:
        return (
            f"{evidence.evidence_id}: ez az ármodell csak belső kontrollforrás; "
            "közvetlen automatikus publikációra nem használható."
        )

    required = {
        "technology",
        "completion_level",
        "package",
        "gross_area_m2",
        "vat_rate",
    }
    if not required.issubset(evidence.price_input):
        return f"{evidence.evidence_id}: hiányos kalkulátor-input."
    pricing_brand = PRICING_BRAND_NAMES.get(brand_id)
    if not pricing_brand:
        return f"{evidence.evidence_id}: ehhez a márkához nincs aktív árkalkulátor."
    result = pricing_repository.calculate_new_build(
        brand=pricing_brand,
        technology=evidence.price_input["technology"],
        completion_level=evidence.price_input["completion_level"],
        package=evidence.price_input["package"],
        gross_area_m2=Decimal(evidence.price_input["gross_area_m2"]),
        vat_rate=Decimal(evidence.price_input["vat_rate"]),
    )
    output_field = evidence.price_output_field or ""
    expected_value = result.get(output_field)
    if not isinstance(expected_value, int) or expected_value != evidence.price_value_huf:
        return f"{evidence.evidence_id}: a publikált ár eltér a kalkulátor kimenetétől."
    digits = re.sub(r"\D", "", " ".join(asset.price_mentions))
    if str(expected_value) not in digits:
        return f"{evidence.evidence_id}: a kalkulált ár nem jelenik meg az asset ármezőiben."
    if not asset.condition_mentions:
        return f"{evidence.evidence_id}: az ár scope-ja/feltételei hiányoznak."
    return None


def evaluate_commercial_prevalidation(
    brand_id: str,
    asset: ContentAsset,
    *,
    registry: dict[str, Any] | None = None,
) -> CommercialPrevalidationResult:
    registry = registry or load_prevalidated_registry()
    registry_version = str(registry["registry_version"])
    registry_sha256 = sha256_text(
        json.dumps(registry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    canonical_brand = canonical_brand_id(brand_id)
    brand_registry = registry.get("brands", {}).get(canonical_brand)
    findings: list[str] = []
    verified: list[str] = []
    covered_categories: set[str] = set()
    covered_claims: set[str] = set()
    covered_visuals: set[str] = set()
    drive_price_verified = False

    if not brand_registry:
        findings.append(f"Ismeretlen vagy nem snapshotolt márka: {canonical_brand}.")
    if asset.action_risk_level > 3:
        findings.append("R4–R7 művelet nem használhat automatikus forrás-elővalidációt.")
    if asset.external_action_type != ExternalActionType.MARKETING_COMMUNICATION:
        findings.append(
            "Külső kötelezettségvállalás, szerződésmódosítás, felelősségelismerés "
            "vagy teljesítésigazolás kötelező emberi R6–R7 művelet."
        )

    for evidence in asset.prevalidated_source_evidence:
        error: str | None
        if not brand_registry:
            error = f"{evidence.evidence_id}: a márka registry-je hiányzik."
        elif evidence.source_type == "website_fragment":
            error = _validate_website_fragment(
                evidence,
                brand_registry=brand_registry,
                registry_version=registry_version,
                asset=asset,
            )
            if error is None:
                covered_claims.add(normalize(evidence.claim_text or ""))
        elif evidence.source_type == "website_visual":
            error = _validate_website_visual(
                evidence,
                brand_registry=brand_registry,
                registry_version=registry_version,
                asset=asset,
            )
            if error is None and evidence.visual_asset_id:
                covered_visuals.add(evidence.visual_asset_id)
        else:
            error = _validate_drive_price(
                evidence,
                registry=registry,
                brand_id=canonical_brand,
                asset=asset,
            )
            drive_price_verified = error is None
        if error:
            findings.append(error)
        else:
            verified.append(evidence.evidence_id)
            covered_categories.add(evidence.category)

    uncovered_claims = [
        claim for claim in asset.factual_claims if normalize(claim) not in covered_claims
    ]
    if uncovered_claims:
        findings.append("Nem elővalidált tényszerű állítás(ok): " + "; ".join(uncovered_claims))
    if asset.price_mentions and not (drive_price_verified or "price" in covered_categories):
        findings.append("Legalább egy árközléshez nincs elővalidált webes vagy Drive-forrás.")
    uncovered_visuals = sorted(set(asset.visual_asset_ids) - covered_visuals)
    if uncovered_visuals:
        findings.append(
            "Nem elővalidált típusház/floorplan vizuál(ok): " + ", ".join(uncovered_visuals)
        )
    if not asset.prevalidated_source_evidence:
        findings.append("Nincs forrás-elővalidációs bizonyíték.")

    gate_coverage = {
        gate_id: any(GATE_BY_CATEGORY.get(category) == gate_id for category in covered_categories)
        for gate_id in (
            "GATE_2_LEGAL_POLICY",
            "GATE_3_FINANCIAL_COMMERCIAL",
            "GATE_4_TECHNICAL_FACTUAL",
        )
    }
    return CommercialPrevalidationResult(
        eligible=not findings,
        registry_version=registry_version,
        registry_sha256=registry_sha256,
        gate_coverage=gate_coverage,
        verified_evidence_ids=tuple(verified),
        findings=tuple(findings),
        metadata={
            "brand_id": canonical_brand,
            "covered_categories": sorted(covered_categories),
            "drive_price_verified": drive_price_verified,
        },
    )
