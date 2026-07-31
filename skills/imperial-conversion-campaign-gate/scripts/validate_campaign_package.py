#!/usr/bin/env python3
"""Fail-closed validator for Imperial campaign release packages."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

REQUIRED_REVIEW_ROLES = {
    "marketing_strategist",
    "direct_response_copywriter",
    "hungarian_language_editor",
    "brand_guardian",
    "creative_director",
    "legal",
    "financial",
}

REQUIRED_ARTIFACT_ROLES = {
    "copy",
    "visual_source",
    "canonical_master",
    "render_1080",
    "subject_mask",
}
ALLOWED_ARTIFACT_ROLES = REQUIRED_ARTIFACT_ROLES | {"platform_export"}

REQUIRED_STRATEGY_FIELDS = {
    "concept_id",
    "target_segment",
    "life_situation",
    "market_problem",
    "fear_or_tension",
    "desired_outcome",
    "product_or_service",
    "primary_offer",
    "brand_specific_mechanism",
    "brand_specific_differentiator",
    "objection_answer",
    "why_now",
    "conversion_event",
    "primary_concept_class",
}

SHARED_SUPPORT_ONLY = {
    "plot_review",
    "engineering_consultation",
    "free_quote",
    "fixed_price",
    "fixed_deadline",
    "fast_construction",
    "transparent_process",
    "helpful_team",
}

FORBIDDEN_CUSTOMER_PHRASES = {
    "házirányt kérek",
    "telket küldök",
    "lehetőséget kérek",
    "projektet indítok",
    "kérem egy kézben",
    "megnézem, hogyan",
    "mindent megszervezünk",
    "akkor kész, amikor költözhető",
    "a ház ne legyen okosabb nálad",
    "terv keret határidő egy asztalon",
    "ne a folyosót fizesd",
}

VAGUE_CTAS = {
    "tovább",
    "érdekel",
    "részletek",
    "megnézem",
    "kérem",
    "indulok",
}


def normalized(text: str) -> str:
    value = unicodedata.normalize("NFKD", text).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_set_digest(entries: list[tuple[str, str]]) -> str:
    payload = "\n".join(f"{path}\t{digest}" for path, digest in sorted(entries))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def require_mapping(
    data: dict[str, Any], key: str, failures: list[str]
) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        failures.append(f"{key}: required object is missing")
        return {}
    return value


def require_text(
    data: dict[str, Any], key: str, context: str, failures: list[str], minimum: int = 3
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or len(value.strip()) < minimum:
        failures.append(f"{context}.{key}: meaningful text is required")
        return ""
    return value.strip()


def load_registry_packages(
    registry: Path | None, manifest: Path
) -> list[dict[str, Any]]:
    if not registry or not registry.exists():
        return []
    packages: list[dict[str, Any]] = []
    for candidate in registry.rglob("campaign-package.json"):
        try:
            if candidate.resolve() == manifest.resolve():
                continue
            packages.append(json.loads(candidate.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return packages


def validate(
    manifest_path: Path, registry: Path | None, stage: str
) -> tuple[dict[str, Any], list[str], list[str], str]:
    failures: list[str] = []
    warnings: list[str] = []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"manifest cannot be read: {exc}"], warnings, ""

    for key in ("brand_id", "campaign_id", "campaign_type", "period", "author_id"):
        require_text(data, key, "root", failures)
    if data.get("schema_version") != "1.0":
        failures.append("schema_version must be 1.0")

    source_hashes = require_mapping(data, "source_hashes", failures)
    for key in ("brand_brief", "visual_guide", "conversion_architecture"):
        value = source_hashes.get(key, "")
        if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", value):
            failures.append(f"source_hashes.{key}: a SHA-256 digest is required")
    if data.get("campaign_type") in {"promotion", "typehouse_promotion"}:
        for key in ("offer_source", "price_source"):
            value = source_hashes.get(key, "")
            if not isinstance(value, str) or not re.fullmatch(
                r"[a-fA-F0-9]{64}", value
            ):
                failures.append(
                    f"source_hashes.{key}: required for promotion campaigns"
                )

    strategy = require_mapping(data, "strategy", failures)
    for key in REQUIRED_STRATEGY_FIELDS:
        require_text(strategy, key, "strategy", failures)
    proof_stack = strategy.get("proof_stack")
    if (
        not isinstance(proof_stack, list)
        or len([p for p in proof_stack if isinstance(p, str) and p.strip()]) < 2
    ):
        failures.append(
            "strategy.proof_stack: at least two concrete proofs are required"
        )
    concept_class = strategy.get("primary_concept_class")
    differentiator = str(strategy.get("brand_specific_differentiator", ""))
    if concept_class in SHARED_SUPPORT_ONLY and (
        len(differentiator) < 60
        or not isinstance(proof_stack, list)
        or len(proof_stack) < 3
    ):
        failures.append(
            "strategy.primary_concept_class: a shared service claim cannot be the primary concept without a substantial brand-specific differentiator and three proofs"
        )

    copy = require_mapping(data, "copy", failures)
    headline = require_text(copy, "headline", "copy", failures)
    support = require_text(copy, "support", "copy", failures)
    cta = require_text(copy, "cta", "copy", failures)
    primary_text = require_text(copy, "primary_text", "copy", failures, minimum=40)
    if word_count(headline) > 10:
        failures.append("copy.headline: more than 10 words")
    if word_count(support) > 18:
        failures.append("copy.support: more than 18 words")
    if not 2 <= word_count(cta) <= 5:
        failures.append("copy.cta: must contain 2-5 words")
    if normalized(cta) in {normalized(item) for item in VAGUE_CTAS}:
        failures.append("copy.cta: vague CTA is not allowed")
    customer_copy = normalized(f"{headline} {support} {cta} {primary_text}")
    for phrase in FORBIDDEN_CUSTOMER_PHRASES:
        if normalized(phrase) in customer_copy:
            failures.append(f"copy: known failed phrase detected: {phrase}")
    if re.search(
        r"\b(kapu|gate|snapshotid|offerversionid|termsversionid)\b", customer_copy
    ):
        failures.append("copy: internal validation jargon is not customer-facing copy")
    candidates = copy.get("concept_candidates")
    rejected = copy.get("rejected_candidates")
    if not isinstance(candidates, list) or len(candidates) < 3:
        failures.append(
            "copy.concept_candidates: at least three alternatives are required"
        )
    if not isinstance(rejected, list) or len(rejected) < 2:
        failures.append(
            "copy.rejected_candidates: at least two rejected alternatives with reasons are required"
        )
    elif any(
        not isinstance(item, dict) or not str(item.get("reason", "")).strip()
        for item in rejected
    ):
        failures.append("copy.rejected_candidates: every rejection requires a reason")

    visual = require_mapping(data, "visual", failures)
    for key in ("canonical_master", "render_1080", "layout_archetype", "subject_mask"):
        require_text(visual, key, "visual", failures)
    numeric_rules = {
        "photo_visible_ratio": (0.75, None),
        "min_text_px": (40, None),
        "headline_lines": (None, 2),
        "support_lines": (None, 2),
        "cta_lines": (1, 1),
        "text_subject_intersections": (0, 0),
        "text_box_overflows": (0, 0),
    }
    for key, (minimum, maximum) in numeric_rules.items():
        value = visual.get(key)
        if not isinstance(value, (int, float)):
            failures.append(f"visual.{key}: numeric evidence is required")
            continue
        if minimum is not None and value < minimum:
            failures.append(f"visual.{key}: {value} is below {minimum}")
        if maximum is not None and value > maximum:
            failures.append(f"visual.{key}: {value} exceeds {maximum}")
    for key in ("ocr_match", "downscale_readable", "official_brand_assets"):
        if visual.get(key) is not True:
            failures.append(f"visual.{key}: must be true")
    if (
        visual.get("gradient_used") is not False
        and visual.get("gradient_exception_approved") is not True
    ):
        failures.append(
            "visual.gradient_used: gradients require an explicit approved exception"
        )
    if (
        data.get("campaign_type") in {"typehouse", "typehouse_promotion"}
        and visual.get("typehouse_image_verified") is not True
    ):
        failures.append(
            "visual.typehouse_image_verified: required for typehouse campaigns"
        )

    program = require_mapping(data, "program_context", failures)
    if program.get("residential_house_brand") is True:
        share = program.get("product_led_share")
        if not isinstance(share, (int, float)) or share < 0.60:
            failures.append(
                "program_context.product_led_share: residential programs require at least 0.60"
            )
    for key in ("concept_unique", "layout_unique"):
        if program.get(key) is not True:
            failures.append(f"program_context.{key}: must be true")
    require_text(program, "cross_brand_registry", "program_context", failures)

    artifacts = data.get("artifacts")
    calculated: list[tuple[str, str]] = []
    artifact_roles: set[str] = set()
    if not isinstance(artifacts, list) or not artifacts:
        failures.append("artifacts: at least one hash-bound artifact is required")
    else:
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                failures.append(f"artifacts[{index}]: object required")
                continue
            relative = artifact.get("path")
            expected = artifact.get("sha256")
            role = artifact.get("role")
            if role not in ALLOWED_ARTIFACT_ROLES:
                failures.append(
                    f"artifacts[{index}].role: unknown or missing artifact role"
                )
            else:
                artifact_roles.add(role)
            if not isinstance(relative, str) or not relative:
                failures.append(f"artifacts[{index}].path: required")
                continue
            target = (manifest_path.parent / relative).resolve()
            if not target.is_file():
                failures.append(f"artifacts[{index}]: missing file {relative}")
                continue
            actual = sha256_file(target)
            if not isinstance(expected, str) or not hmac.compare_digest(
                actual, expected.casefold()
            ):
                failures.append(f"artifacts[{index}]: SHA-256 mismatch for {relative}")
            calculated.append((relative, actual))
        missing_artifact_roles = REQUIRED_ARTIFACT_ROLES - artifact_roles
        if missing_artifact_roles:
            failures.append(
                "artifacts: missing required roles: "
                + ", ".join(sorted(missing_artifact_roles))
            )
    set_digest = artifact_set_digest(calculated) if calculated else ""

    reviews = data.get("reviews")
    seen_roles: dict[str, dict[str, Any]] = {}
    reviewer_ids: list[str] = []
    if not isinstance(reviews, list):
        failures.append("reviews: required list")
    else:
        for review in reviews:
            if not isinstance(review, dict):
                failures.append("reviews: every review must be an object")
                continue
            role = str(review.get("role", ""))
            if role in seen_roles:
                failures.append(f"reviews: duplicate role {role}")
            seen_roles[role] = review
        for role in sorted(REQUIRED_REVIEW_ROLES):
            review = seen_roles.get(role)
            if not review:
                failures.append(f"reviews: missing {role}")
                continue
            reviewer_id = str(review.get("reviewer_id", "")).strip()
            if not reviewer_id:
                failures.append(f"reviews.{role}: reviewer_id required")
            reviewer_ids.append(reviewer_id)
            if review.get("decision") != "PASS":
                failures.append(f"reviews.{role}: decision must be PASS")
            if set_digest and review.get("artifact_set_sha256") != set_digest:
                failures.append(
                    f"reviews.{role}: review is not bound to the current artifact set"
                )
    author_id = str(data.get("author_id", ""))
    if author_id and author_id in reviewer_ids:
        failures.append("reviews: author cannot review their own work")
    if len([item for item in reviewer_ids if item]) != len(
        {item for item in reviewer_ids if item}
    ):
        failures.append("reviews: reviewer identities must be distinct")

    other_packages = load_registry_packages(registry, manifest_path)
    threshold = program.get("allowed_copy_similarity", 0.62)
    if not isinstance(threshold, (int, float)) or threshold > 0.72:
        failures.append(
            "program_context.allowed_copy_similarity: must be numeric and no greater than 0.72"
        )
        threshold = 0.62
    current_copy = normalized(f"{headline} {support} {primary_text}")
    for other in other_packages:
        if other.get("brand_id") == data.get("brand_id"):
            continue
        other_strategy = (
            other.get("strategy") if isinstance(other.get("strategy"), dict) else {}
        )
        other_visual = (
            other.get("visual") if isinstance(other.get("visual"), dict) else {}
        )
        other_copy_data = (
            other.get("copy") if isinstance(other.get("copy"), dict) else {}
        )
        if strategy.get("concept_id") and strategy.get(
            "concept_id"
        ) == other_strategy.get("concept_id"):
            failures.append(
                f"cross-brand: concept_id reused by {other.get('brand_id')}"
            )
        if visual.get("layout_archetype") and visual.get(
            "layout_archetype"
        ) == other_visual.get("layout_archetype"):
            failures.append(
                f"cross-brand: layout_archetype reused by {other.get('brand_id')}"
            )
        other_text = normalized(
            " ".join(
                str(other_copy_data.get(k, ""))
                for k in ("headline", "support", "primary_text")
            )
        )
        if current_copy and other_text:
            similarity = SequenceMatcher(None, current_copy, other_text).ratio()
            if similarity > threshold:
                failures.append(
                    f"cross-brand: copy similarity {similarity:.3f} exceeds {threshold:.3f} against {other.get('brand_id')}"
                )

    release = require_mapping(data, "release", failures)
    if release.get("r6_r7") != "HUMAN_ONLY":
        failures.append("release.r6_r7: must be HUMAN_ONLY")
    if "release_token" in release:
        failures.append(
            "release.release_token: tokens may only be written by the validator"
        )
    if stage == "creative" and release.get("publication_authorized") is not False:
        failures.append(
            "release.publication_authorized: must remain false at creative stage"
        )
    if stage == "publish":
        if release.get("publication_authorized") is not True:
            failures.append(
                "release.publication_authorized: must be true for publish stage"
            )
        approval = release.get("human_approval")
        if not isinstance(approval, dict):
            failures.append("release.human_approval: required for publication")
        else:
            if approval.get("decision") != "APPROVE":
                failures.append("release.human_approval.decision: must be APPROVE")
            if approval.get("artifact_set_sha256") != set_digest:
                failures.append(
                    "release.human_approval: approval is not bound to the current artifact set"
                )
            require_text(approval, "reviewer_id", "release.human_approval", failures)
            require_text(approval, "approved_at", "release.human_approval", failures)
        if not os.environ.get("IMPERIAL_RELEASE_HMAC_KEY"):
            failures.append(
                "IMPERIAL_RELEASE_HMAC_KEY is missing from secret management"
            )

    return data, failures, warnings, set_digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--stage", choices=("creative", "publish"), default="creative")
    parser.add_argument("--token-out", type=Path)
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args()

    data, failures, warnings, set_digest = validate(
        args.manifest.resolve(), args.registry, args.stage
    )
    status = (
        "BLOCKED"
        if failures
        else (
            "PUBLICATION_AUTHORIZED"
            if args.stage == "publish"
            else "CREATIVE_READY_PUBLICATION_BLOCKED"
        )
    )
    report = {
        "status": status,
        "stage": args.stage,
        "brand_id": data.get("brand_id") if data else None,
        "campaign_id": data.get("campaign_id") if data else None,
        "artifact_set_sha256": set_digest or None,
        "failures": failures,
        "warnings": warnings,
    }

    if not failures and args.stage == "publish":
        if not args.token_out:
            report["status"] = "BLOCKED"
            report["failures"].append("--token-out is required at publish stage")
        else:
            payload = {
                "brand_id": data["brand_id"],
                "campaign_id": data["campaign_id"],
                "artifact_set_sha256": set_digest,
                "human_reviewer_id": data["release"]["human_approval"]["reviewer_id"],
                "approved_at": data["release"]["human_approval"]["approved_at"],
                "r6_r7": "HUMAN_ONLY",
            }
            canonical = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            secret = os.environ["IMPERIAL_RELEASE_HMAC_KEY"].encode("utf-8")
            payload["hmac_sha256"] = hmac.new(
                secret, canonical, hashlib.sha256
            ).hexdigest()
            args.token_out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    if args.report_out:
        args.report_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
