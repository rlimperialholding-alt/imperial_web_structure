from __future__ import annotations

import hashlib
import json
import re

from .models import (
    ContentEvaluationRequest,
    Decision,
    DimensionScore,
    EvaluationResult,
    Finding,
    GateResult,
    Severity,
)
from .rules import (
    FORMAL_MARKERS,
    GENERIC_CTAS,
    GENERIC_PHRASES,
    INFORMAL_MARKERS,
    contains_phrases,
    duplicate_values,
    normalize,
    numeric_signal_count,
    sentence_lengths,
    tricolon_count,
)


def _finding(
    code: str,
    message: str,
    severity: Severity = Severity.WARNING,
    *,
    location: str | None = None,
    source: str | None = None,
    repair: str | None = None,
) -> Finding:
    return Finding(
        code=code,
        message=message,
        severity=severity,
        location=location,
        violated_source=source,
        repair_instruction=repair,
    )


def _dimension(name: str, score: int, findings: list[Finding]) -> DimensionScore:
    bounded = max(0, min(score, 10))
    return DimensionScore(
        name=name,
        score=bounded,
        passed=bounded >= 8 and not any(item.severity == Severity.CRITICAL for item in findings),
        findings=findings,
    )


def _content_hash(request: ContentEvaluationRequest) -> str:
    payload = request.asset.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _expert_review_integrity_findings(
    request: ContentEvaluationRequest,
) -> list[Finding]:
    review = request.editorial_review
    findings: list[Finding] = []
    if review.reviewed_asset_id != request.asset.asset_id:
        findings.append(
            _finding(
                "EXPERT_REVIEW_ASSET_MISMATCH",
                "A szakértői jegyzőkönyv másik tartalmi eszközhöz tartozik.",
                Severity.CRITICAL,
            )
        )
    if review.reviewed_content_sha256 != _content_hash(request):
        findings.append(
            _finding(
                "EXPERT_REVIEW_HASH_MISMATCH",
                "A szakértői jegyzőkönyv nem az aktuális tartalomhashhez tartozik.",
                Severity.CRITICAL,
            )
        )
    if review.reviewer_run_id == review.generation_run_id:
        findings.append(
            _finding(
                "REVIEW_INDEPENDENCE_FAILED",
                "A generáló és ellenőrző futás nem lehet azonos.",
                Severity.CRITICAL,
            )
        )
    return findings


def _deterministic_hungarian_findings(text: str) -> list[Finding]:
    """Fail closed on known nonsense, internal shorthand and ambiguous offer syntax."""

    patterns = (
        (
            r"\botthona?\s+kör[ée]\s+zárul",
            "UNNATURAL_HOME_CLOSURE_METAPHOR",
            ("Az „otthona köré zárul” nem közérthető magyar vagy bevett építőipari megfogalmazás."),
            ("Ne metaforával, hanem az ellenőrzés pontos tárgyával és időpontjával fogalmazzon."),
        ),
        (
            r"\bkész\s+kertkapcsolat\w*\b",
            "UNEXPLAINED_OFFER_SHORTHAND",
            (
                "A „kész kertkapcsolat” belső kampányelnevezés, önmagában nem mondja meg, "
                "mit kap az ügyfél."
            ),
            (
                "Nevezze meg a térkövezés területét, az alapréteget, a szegélyezést, "
                "a kivitelezést és a választási feltételeket."
            ),
        ),
        (
            r"\b(?:nem\s+)?ködös\s+életérzés\b",
            "INTERNAL_CRITIQUE_LEAKED_TO_CONSUMER_COPY",
            (
                "A „ködös életérzés” belső szövegkritikai megjegyzés, nem fogyasztói "
                "marketingüzenet."
            ),
            (
                "Törölje a szerkesztési kommentárt, és közvetlenül az ügyfél előnyét, "
                "annak okát és a bizonyítékot fogalmazza meg."
            ),
        ),
        (
            r"\bnem\s+hangzatos\s+ígéret(?:ként)?\b",
            "INTERNAL_CRITIQUE_LEAKED_TO_CONSUMER_COPY",
            ("A „nem hangzatos ígéret” szerkesztői önigazolás, nem fogyasztói marketingüzenet."),
            (
                "Hagyja el a kommentárt, és közölje közvetlenül a konkrét vállalást "
                "és annak bizonyítékát."
            ),
        ),
        (
            r"\ba\s+vállalás\b.{0,100}\bkapcsolódik\b",
            "ADMINISTRATIVE_OFFER_LANGUAGE",
            (
                "Az „a vállalás ... kapcsolódik” adminisztratív, személytelen "
                "megfogalmazás, nem piacképes ajánlati mondat."
            ),
            (
                "Fogalmazza át közvetlen ügyfélértékre, például: „Fix ár, fix "
                "határidő, tervezés az árban.”"
            ),
        ),
        (
            r"\bmagyar\s+brands\b",
            "NONCANONICAL_AWARD_NAME",
            "A díj hivatalos márkaneve egybeírandó: MagyarBrands.",
            "Használja a hivatalos „MagyarBrands” írásmódot.",
        ),
    )
    findings: list[Finding] = []
    for pattern, code, message, repair in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            findings.append(
                _finding(
                    code,
                    message,
                    Severity.CRITICAL,
                    repair=repair,
                )
            )
    normalized = normalize(text)
    causal_markers = {
        "90 nap",
        "120 nap",
        "gyors kivitelezés",
        "üzemben készül",
        "kevesebb építési idő",
    }
    if "több idő élni" in normalized and not any(marker in normalized for marker in causal_markers):
        findings.append(
            _finding(
                "UNEXPLAINED_LIFESTYLE_PROMISE",
                (
                    "A „több idő élni” önmagában levegőben lógó ígéret: nem derül ki, "
                    "mihez képest és milyen okból ad több időt."
                ),
                Severity.CRITICAL,
                repair=(
                    "Nevezze meg a bizonyított mechanizmust, például a tervezéssel együtt "
                    "vállalt kivitelezési időt vagy az üzemi előregyártást."
                ),
            )
        )
    if re.search(r"(?<!\w)aaa(?!\w)", normalized) and not re.search(
        r"(?<!\w)aaa(?!\w).{0,90}(panaszmentességi|panaszmentes|igazolás|minősítés|kategóriás)",
        normalized,
    ):
        findings.append(
            _finding(
                "UNEXPLAINED_TRUST_ACRONYM",
                (
                    "Az önálló „AAA” nem közérthető fogyasztói állítás; nem mondja meg, "
                    "milyen minősítést vagy igazolást jelent."
                ),
                Severity.CRITICAL,
                repair=(
                    "A logót használja felirat nélkül, vagy írja ki teljesen: "
                    "„AAA kategóriás panaszmentességi igazolás”."
                ),
            )
        )
    return findings


def evaluate_content(request: ContentEvaluationRequest) -> EvaluationResult:
    brief = request.brief
    asset = request.asset
    sources = request.sources
    full_text = " ".join([asset.title, asset.body, asset.cta, asset.slogan])
    normalized_text = normalize(full_text)
    dimensions: list[DimensionScore] = []
    integrity: list[Finding] = []

    findings: list[Finding] = []
    score = 10
    if set(asset.detected_brand_ids) != {brief.brand_id}:
        score = 0
        findings.append(
            _finding(
                "BRAND_CONTAMINATION",
                "Az asset más márka tartalmát vagy azonosítóját is tartalmazza.",
                Severity.CRITICAL,
                source="brand-master",
                repair="Távolítsa el az idegen márka minden szöveges és vizuális elemét.",
            )
        )
    missing_concepts = [
        concept
        for concept in sources.required_brand_concepts
        if normalize(concept) not in normalized_text
    ]
    if missing_concepts:
        score -= min(4, len(missing_concepts))
        findings.append(
            _finding(
                "BRAND_CONCEPT_MISSING",
                f"Hiányzó márkamechanizmusok: {', '.join(missing_concepts)}.",
                repair="A releváns márkamechanizmust természetes módon építse be.",
            )
        )
    wrong_tone = contains_phrases(full_text, sources.forbidden_brand_phrases)
    if wrong_tone:
        score = 0
        findings.append(
            _finding(
                "BRAND_TONE_VIOLATION",
                f"Tiltott márkahang: {', '.join(wrong_tone)}.",
                Severity.CRITICAL,
            )
        )
    if sources.brand_addressing == "formal" and contains_phrases(full_text, INFORMAL_MARKERS):
        score = 0
        findings.append(
            _finding(
                "ADDRESSING_MISMATCH",
                "A magázó márkahang tegező fordulatot tartalmaz.",
                Severity.CRITICAL,
            )
        )
    if sources.brand_addressing == "informal" and contains_phrases(full_text, FORMAL_MARKERS):
        score = 0
        findings.append(
            _finding(
                "ADDRESSING_MISMATCH",
                "A tegező márkahang magázó fordulatot tartalmaz.",
                Severity.CRITICAL,
            )
        )
    dimensions.append(_dimension("Brand Voice Fit", score, findings))

    findings = []
    score = 10
    findings.extend(_expert_review_integrity_findings(request))
    findings.extend(_deterministic_hungarian_findings(full_text))
    if brief.brand_id == "danish-fabrik" and re.search(
        r"\b(?:díjmentes\s+tervezés|tervezési\s+díj\s+nélkül)\b",
        normalized_text,
    ):
        findings.append(
            _finding(
                "DANISH_INCLUDED_DESIGN_WORDING_REQUIRED",
                (
                    "A Danish Fabrik tervezése nem „díjmentes”: a fogyasztói "
                    "megfogalmazás szerint a tervezés az ár része."
                ),
                Severity.CRITICAL,
                repair="Használja ezt: „Fix ár, fix határidő, tervezés az árban.”",
            )
        )
    lengths = sentence_lengths(full_text)
    if len(lengths) >= 4 and len(set(lengths)) <= 2:
        score -= 2
        findings.append(_finding("MONOTONOUS_RHYTHM", "A mondatok ritmusa túl egyforma."))
    if tricolon_count(full_text) > 2:
        score -= 2
        findings.append(
            _finding("TRICOLON_OVERUSE", "Túl sok sablonos háromtagú felsorolás szerepel.")
        )
    if normalized_text.count("nem csak") + normalized_text.count("nemcsak") > 1:
        score -= 2
        findings.append(_finding("NOT_ONLY_OVERUSE", "Túlhasznált „nemcsak…, hanem…” szerkezet."))
    if request.editorial_review.decision != Decision.APPROVED:
        score = 0
        findings.append(
            _finding(
                "EDITORIAL_REVIEW_FAILED",
                "A független magyar szerkesztői review nem hagyta jóvá a szöveget.",
                Severity.CRITICAL,
            )
        )
    if request.editorial_review.reviewer_run_id == request.editorial_review.generation_run_id:
        score = 0
        findings.append(
            _finding(
                "REVIEW_INDEPENDENCE_FAILED",
                "A generáló és ellenőrző futás nem lehet azonos.",
                Severity.CRITICAL,
            )
        )
    language_scores = (
        request.editorial_review.idiomatic_hungarian_score,
        request.editorial_review.grammar_score,
        request.editorial_review.semantic_clarity_score,
        request.editorial_review.terminology_score,
    )
    score = min(score, min(language_scores))
    if min(language_scores) < 9:
        score = 0
        findings.append(
            _finding(
                "HUNGARIAN_EXPERT_THRESHOLD_FAILED",
                "A magyar nyelvi szakértői minimum minden dimenzióban 9/10.",
                Severity.CRITICAL,
            )
        )
    if (
        request.editorial_review.ambiguous_phrases
        or request.editorial_review.unnatural_phrases
        or request.editorial_review.required_repairs
        or request.editorial_review.findings
    ):
        score = 0
        findings.append(
            _finding(
                "HUNGARIAN_EXPERT_OPEN_FINDINGS",
                "A magyar nyelvi szakértői jegyzőkönyv nyitott hibát tartalmaz.",
                Severity.CRITICAL,
            )
        )
    dimensions.append(_dimension("Natural Hungarian", score, findings))

    findings = []
    score = 10
    if len(asset.title.split()) < 5:
        score -= 3
        findings.append(
            _finding(
                "WEAK_HOOK", "A címsor nem teszi felismerhetővé a helyzetet vagy az ajánlatot."
            )
        )
    mechanism_parts = [
        normalize(part) for part in brief.unique_mechanism.split("+") if normalize(part)
    ]
    if not mechanism_parts or any(part not in normalized_text for part in mechanism_parts):
        score -= 3
        findings.append(
            _finding("UNIQUE_MECHANISM_MISSING", "Az egyedi mechanizmus nem jelenik meg.")
        )
    if not asset.objection_ids_handled:
        score -= 2
        findings.append(_finding("NO_OBJECTION_SIGNAL", "A szöveg nem jelöl kezelt kifogást."))
    marketing_scores = (
        request.editorial_review.hook_strength_score,
        request.editorial_review.offer_clarity_score,
        request.editorial_review.specificity_score,
        request.editorial_review.persuasion_score,
        request.editorial_review.brand_voice_score,
        request.editorial_review.conversion_path_score,
    )
    score = min(score, min(marketing_scores))
    if min(marketing_scores) < 9:
        score = 0
        findings.append(
            _finding(
                "MARKETING_EXPERT_THRESHOLD_FAILED",
                "Az online marketing-szövegírói minimum minden dimenzióban 9/10.",
                Severity.CRITICAL,
            )
        )
    if request.editorial_review.unsupported_claims:
        score = 0
        findings.append(
            _finding(
                "MARKETING_EXPERT_UNSUPPORTED_CLAIMS",
                "A szakértői jegyzőkönyv alá nem támasztott állítást jelöl.",
                Severity.CRITICAL,
            )
        )
    dimensions.append(_dimension("Direct Response Strength", score, findings))

    findings = []
    score = 10
    version_checks = {
        "OFFER_VERSION_MISMATCH": (asset.offer_version_id_used, brief.offer_version_id),
        "PRICE_VERSION_MISMATCH": (asset.price_snapshot_id_used, brief.price_snapshot_id),
        "TERMS_VERSION_MISMATCH": (asset.terms_version_id_used, brief.terms_version_id),
    }
    for code, (actual, expected) in version_checks.items():
        if actual != expected:
            score = 0
            findings.append(
                _finding(code, f"Eltérő vagy lejárt üzleti verzió: {actual}.", Severity.CRITICAL)
            )
    if not (
        sources.active_offer
        and sources.active_price
        and sources.active_terms
        and sources.active_product
    ):
        score = 0
        findings.append(
            _finding(
                "INACTIVE_OFFER_CORE",
                "Az ajánlat, ár, feltétel vagy termék nem aktív.",
                Severity.CRITICAL,
            )
        )
    if not asset.condition_mentions:
        score -= 2
        findings.append(
            _finding(
                "OFFER_CONDITIONS_MISSING", "Az ajánlat feltétele vagy scope-ja nem jelenik meg."
            )
        )
    dimensions.append(_dimension("Offer Clarity", score, findings))

    findings = []
    score = 10
    vague = contains_phrases(full_text, GENERIC_PHRASES)
    if vague:
        score -= min(8, len(vague) * 2)
        findings.append(
            _finding(
                "GENERIC_LANGUAGE",
                f"Generikus vagy elhasznált fordulatok: {', '.join(vague)}.",
                repair="Cserélje konkrét mechanizmusra, eredményre vagy bizonyítékra.",
            )
        )
    if numeric_signal_count(full_text) == 0 and not asset.factual_claims:
        score -= 3
        findings.append(
            _finding("NO_SPECIFIC_EVIDENCE", "Nincs konkrét adat vagy ellenőrizhető tény.")
        )
    dimensions.append(_dimension("Specificity", score, findings))

    findings = []
    score = 10
    missing_claims = sorted(set(brief.claim_ids) - set(asset.claim_ids_used))
    missing_proofs = sorted(set(brief.proof_ids) - set(asset.proof_ids_used))
    unresolved_claims = sorted(set(asset.claim_ids_used) - set(sources.claims_resolved))
    unresolved_proofs = sorted(set(asset.proof_ids_used) - set(sources.proofs_resolved))
    if missing_claims or missing_proofs or unresolved_claims or unresolved_proofs:
        score = 0
        findings.append(
            _finding(
                "CLAIM_PROOF_COVERAGE_FAILED",
                (
                    f"Hiányzó ClaimID: {missing_claims}; hiányzó ProofID: {missing_proofs}; "
                    f"feloldatlan ClaimID: {unresolved_claims}; "
                    f"feloldatlan ProofID: {unresolved_proofs}."
                ),
                Severity.CRITICAL,
            )
        )
    dimensions.append(_dimension("Proof Coverage", score, findings))

    findings = []
    score = 10
    missing_objections = sorted(set(brief.primary_objection_ids) - set(asset.objection_ids_handled))
    if missing_objections:
        score -= min(6, len(missing_objections) * 3)
        findings.append(
            _finding(
                "OBJECTION_COVERAGE_GAP",
                f"Nem kezelt elsődleges kifogások: {', '.join(missing_objections)}.",
            )
        )
    if normalize(brief.risk_reversal) not in normalized_text:
        score -= 2
        findings.append(
            _finding("RISK_REVERSAL_MISSING", "A brief kockázatcsökkentő eleme nem jelenik meg.")
        )
    dimensions.append(_dimension("Objection Handling", score, findings))

    findings = []
    score = 10
    if asset.landing_message_match_id_used != brief.landing_message_match_id:
        score = 0
        findings.append(
            _finding(
                "MESSAGE_MATCH_FAILED",
                "A kampány- és landingüzenet azonosítója eltér.",
                Severity.CRITICAL,
            )
        )
    dimensions.append(_dimension("Message Match", score, findings))

    findings = []
    score = 10
    if asset.cta_type_used != brief.primary_cta_type:
        score = 0
        findings.append(
            _finding(
                "CTA_TYPE_MISMATCH",
                "A CTA nem a briefben jóváhagyott következő lépés.",
                Severity.CRITICAL,
            )
        )
    bad_cta = contains_phrases(asset.cta, GENERIC_CTAS)
    if bad_cta:
        score = 0
        findings.append(
            _finding(
                "GENERIC_CTA",
                f"Tiltott vagy általános CTA: {', '.join(bad_cta)}.",
                Severity.CRITICAL,
            )
        )
    if len(asset.cta.split()) < 3:
        score -= 2
        findings.append(
            _finding("CTA_TOO_SHORT", "A CTA nem nevezi meg a következő lépés eredményét.")
        )
    dimensions.append(_dimension("CTA Strength", score, findings))

    findings = []
    score = 10
    if any(length > 38 for length in lengths):
        score -= 2
        findings.append(_finding("SENTENCE_TOO_LONG", "Legalább egy mondat 38 szónál hosszabb."))
    duplicate_text = duplicate_values([block.text for block in asset.content_blocks])
    duplicate_layout = duplicate_values([block.layout_signature for block in asset.content_blocks])
    if duplicate_text:
        score = 0
        findings.append(
            _finding(
                "DUPLICATE_CONTENT_BLOCK", "Azonos tartalmú blokkok ismétlődnek.", Severity.CRITICAL
            )
        )
    if duplicate_layout:
        score = 0
        findings.append(
            _finding(
                "DUPLICATE_LAYOUT_BLOCK",
                "Azonos elrendezésű blokkok ismétlődnek.",
                Severity.CRITICAL,
            )
        )
    dimensions.append(_dimension("Readability & Rhythm", score, findings))

    if not sources.source_resolution_pass or sources.source_conflicts:
        integrity.append(
            _finding(
                "SOURCE_RESOLUTION_FAILED",
                "Hiányos vagy ellentmondásos kanonikus források.",
                Severity.CRITICAL,
            )
        )
    promotion_required = (
        brief.monthly_promotion_copy_required or sources.monthly_promotion_copy_required
    )
    if brief.monthly_promotion_copy_required != sources.monthly_promotion_copy_required:
        integrity.append(
            _finding(
                "PROMOTION_SOURCE_MISMATCH",
                "A brief és a kanonikus forrás eltérően jelöli a havi akció kötelezőségét.",
                Severity.CRITICAL,
            )
        )
    if promotion_required:
        expected_promotion_id = sources.monthly_promotion_id or brief.monthly_promotion_id
        if (
            not expected_promotion_id
            or brief.monthly_promotion_id != expected_promotion_id
            or asset.monthly_promotion_id_used != expected_promotion_id
        ):
            integrity.append(
                _finding(
                    "MONTHLY_PROMOTION_ID_MISMATCH",
                    "A hirdetés nem az aktív havi akció azonosítóját használja.",
                    Severity.CRITICAL,
                )
            )
        promotion_copy = (asset.monthly_promotion_copy_text or "").strip()
        if not promotion_copy:
            integrity.append(
                _finding(
                    "MONTHLY_PROMOTION_COPY_MISSING",
                    "Az aktív havi akció nem szerepel a hirdetésszövegben.",
                    Severity.CRITICAL,
                )
            )
        elif asset.monthly_promotion_copy_position != 0 or not normalize(asset.body).startswith(
            normalize(promotion_copy)
        ):
            integrity.append(
                _finding(
                    "MONTHLY_PROMOTION_NOT_FIRST",
                    "A havi akciónak a hirdetésszöveg legelső blokkjában kell szerepelnie.",
                    Severity.CRITICAL,
                )
            )
        if not sources.monthly_promotion_publication_allowed:
            integrity.append(
                _finding(
                    "MONTHLY_PROMOTION_APPROVAL_PENDING",
                    "A havi akció előkészíthető, de a szükséges pénzügyi és vezetői "
                    "jóváhagyások nélkül nem publikálható.",
                    Severity.CRITICAL,
                )
            )
    elif (
        asset.monthly_promotion_id_used
        or asset.monthly_promotion_copy_text
        or asset.monthly_promotion_copy_position is not None
    ):
        integrity.append(
            _finding(
                "UNVALIDATED_MONTHLY_PROMOTION",
                "A hirdetés olyan havi akciót használ, amelyhez nincs aktív forrás.",
                Severity.CRITICAL,
            )
        )
    if not (brief.valid_from <= request.evaluated_on <= brief.valid_until):
        integrity.append(
            _finding(
                "BRIEF_EXPIRED", "A CopyBrief nem érvényes az ellenőrzés napján.", Severity.CRITICAL
            )
        )
    if (
        asset.slogan != brief.required_slogan
        or asset.slogan_version_used != brief.required_slogan_version
    ):
        integrity.append(
            _finding(
                "SLOGAN_MISMATCH",
                "A szlogen szövege vagy verziója nem kanonikus.",
                Severity.CRITICAL,
            )
        )
    forbidden = contains_phrases(full_text, set(brief.forbidden_phrases) | GENERIC_PHRASES)
    if forbidden:
        integrity.append(
            _finding(
                "FORBIDDEN_LANGUAGE",
                f"Tiltott fordulatok: {', '.join(forbidden)}.",
                Severity.CRITICAL,
            )
        )
    if set(brief.required_keywords) - set(asset.required_keywords_used):
        integrity.append(
            _finding(
                "REQUIRED_KEYWORDS_MISSING",
                "Nem minden kötelező kulcsszó szerepel.",
                Severity.CRITICAL,
            )
        )
    if set(asset.visual_asset_ids) - set(sources.visuals_resolved):
        integrity.append(
            _finding(
                "VISUAL_SOURCE_OR_RIGHTS_MISSING",
                "Feloldatlan vagy nem engedélyezett vizuális asset.",
                Severity.CRITICAL,
            )
        )
    if asset.visual_asset_ids and (
        asset.visual_quality_score is None
        or asset.visual_quality_score < 92
        or asset.visual_findings
    ):
        integrity.append(
            _finding(
                "VISUAL_QUALITY_FAILED",
                "A képi anyag nem érte el a 92 pontos vizuális minimumot vagy nyitott hibája van.",
                Severity.CRITICAL,
            )
        )

    all_findings = [
        finding for dimension in dimensions for finding in dimension.findings
    ] + integrity
    total_score = sum(dimension.score for dimension in dimensions)
    critical = any(finding.severity == Severity.CRITICAL for finding in all_findings)
    passed = (
        total_score >= 92 and all(dimension.passed for dimension in dimensions) and not critical
    )
    final_decision = Decision.APPROVED if passed else Decision.RETURN_FOR_REVISION

    repair_brief = list(
        dict.fromkeys(
            finding.repair_instruction or finding.message
            for finding in all_findings
            if finding.severity != Severity.INFO
        )
    )
    return EvaluationResult(
        total_score=total_score,
        dimensions=dimensions,
        gate_1=GateResult(
            gate_id="GATE_1_MARKETING_QUALITY",
            agent_id="AGT-017",
            decision=final_decision,
            relevance=True,
            certainty="HIGH",
            findings=all_findings,
            source_versions=sources.source_versions,
        ),
        final_decision=final_decision,
        publication_blocked=not passed,
        repair_brief=repair_brief,
        metadata={
            "asset_id": asset.asset_id,
            "copy_brief_id": brief.copy_brief_id,
            "brand_id": brief.brand_id,
            "editorial_model_version": request.editorial_review.model_version,
            "editorial_prompt_version": request.editorial_review.prompt_version,
            "expert_review_id": request.editorial_review.reviewer_run_id,
            "expert_reviewer_identity": request.editorial_review.reviewer_identity,
            "expert_reviewer_type": request.editorial_review.reviewer_type,
            "expert_review_content_sha256": request.editorial_review.reviewed_content_sha256,
            "expert_language_approved": (
                request.editorial_review.decision == Decision.APPROVED
                and next(
                    dimension for dimension in dimensions if dimension.name == "Natural Hungarian"
                ).passed
                and min(
                    request.editorial_review.idiomatic_hungarian_score,
                    request.editorial_review.grammar_score,
                    request.editorial_review.semantic_clarity_score,
                    request.editorial_review.terminology_score,
                )
                >= 9
            ),
            "expert_marketing_approved": (
                request.editorial_review.decision == Decision.APPROVED
                and next(
                    dimension
                    for dimension in dimensions
                    if dimension.name == "Direct Response Strength"
                ).passed
                and min(
                    request.editorial_review.hook_strength_score,
                    request.editorial_review.offer_clarity_score,
                    request.editorial_review.specificity_score,
                    request.editorial_review.persuasion_score,
                    request.editorial_review.brand_voice_score,
                    request.editorial_review.conversion_path_score,
                )
                >= 9
            ),
        },
    )
