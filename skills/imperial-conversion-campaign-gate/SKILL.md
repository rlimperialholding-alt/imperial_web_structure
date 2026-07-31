---
name: imperial-conversion-campaign-gate
description: Enforce fail-closed, brand-specific, conversion-led planning, Hungarian direct-response copywriting, typehouse/product advertising, editable creative assembly, cross-brand separation, rendered visual QA, and publication release controls for Imperial Intelligence marketing campaigns. Use whenever Codex plans, writes, generates, reviews, edits, exports, approves, registers, uploads, or publishes advertising, social, landing-page, carousel, lead-form, promotion, typehouse, image, video, or campaign content for any Imperial brand.
---

# Imperial Conversion Campaign Gate

Treat this skill as a release policy, not advice. Never mark an artifact ready, register it as complete, upload it, or publish it unless every required gate passes against the final rendered artifact.

## Non-negotiable outcome

Create a campaign that:

- sells the brand's actual product, capacity or service;
- starts from a real target-market problem, fear, desire or decision barrier;
- presents a specific offer, proof, competitive advantage and next step;
- is unmistakably different from every other active Imperial brand;
- uses natural, persuasive Hungarian written at professional direct-response level;
- keeps product and typehouse imagery visually dominant;
- cannot reach publication through an unvalidated path.

Do not confuse a supporting feature with a campaign concept. Examples such as efficient floor area, plot review, consultation, engineering support, fixed price or fast construction may support an offer. They are not automatically a sufficient primary concept.

## Required source load

Before ideation, load the current versions of:

1. brand positioning and visual manual;
2. conversion architecture and copy rules;
3. active offer, promotion and pricing source;
4. approved USP, proof, guarantee and reference registry;
5. typehouse/product images, plans and rights metadata;
6. current cross-brand campaign registry;
7. previously approved benchmark creatives and copy.

Record each source path or ID and SHA-256 in `campaign-package.json`. Missing, contradictory or stale commercial data must fail closed. Never invent an offer, price, guarantee, deadline, reference or promotion.

Read [references/conversion-doctrine.md](references/conversion-doctrine.md) before planning copy. Read [references/brand-separation.md](references/brand-separation.md) before selecting a concept or layout. Read [references/release-contract.md](references/release-contract.md) before assembling or releasing files. Read [references/known-failure-patterns.md](references/known-failure-patterns.md) during every review.

## Mandatory workflow

### 1. Build the commercial strategy before copy

Write at least three genuinely different campaign concepts. For each, state:

- target segment and life situation;
- urgent problem or fear;
- desired outcome;
- product or service being sold;
- offer and reason to act;
- brand-specific mechanism;
- proof stack;
- objection answered;
- emotional and rational payoff;
- CTA and conversion event.

Reject concepts that merely restate a minor website feature. For residential construction brands, keep the campaign program product-led: at least 60% of active creatives must advertise a real typehouse, house family, building capacity or concrete construction offer unless the current brand strategy explicitly overrides this ratio.

Include life-stage filtering and talking-house/product-personality concepts where they fit the brand. Do not default every brand to plot checks, engineer consultations or free quote campaigns.

### 2. Pass the strategy gate

The marketing strategist must reject a concept if any answer is vague, generic, interchangeable with another brand, unsupported, or unlikely to motivate a qualified buyer.

Require a single-sentence answer to: "Why would this target customer stop, care and act now, and why with this brand?"

If that answer is not specific and persuasive, stop. Do not write final copy.

### 3. Write copy in a separate pass

Generate multiple headline, lead, body and CTA variants from the approved strategy. Write new language; do not slavishly copy source phrases. Use source wording verbatim only when it is already the strongest and most accurate choice.

Prefer concrete Hungarian verbs, buyer situations, observable benefits, credible proof and an unambiguous next step. Keep legal limitations out of the image unless legally mandatory; place necessary detail in the ad body or landing page.

### 4. Pass independent copy gates

Require separate PASS decisions from:

- Hungarian language editor;
- direct-response copywriter;
- content marketing strategist;
- brand guardian.

Reviewers must be distinct from the author and from one another. Reject dry brochure language, internal jargon, tautology, vague atmosphere, generic claims, weak CTA, translation-like Hungarian, unsupported superlatives, and messages that could be relabeled for another brand.

Do not soften a FAIL into PASS because a later version is merely better. PASS means publication-quality.

### 5. Create imagery separately

Generate or select the image without baked-in copy. When advertising a specific typehouse, use its verified image and plan; never substitute a generic AI house.

Create alternative visual directions in separate generation runs. Do not generate an A/B/C set as a single composite run.

### 6. Assemble in deterministic editable format

Use editable SVG or HTML as the canonical master. Use explicit line breaks and coordinates. Treat PPTX as an editable derivative, not the only layout authority.

Apply these hard constraints:

- visible photo area at least 75%;
- zero intersection between text/panel/CTA geometry and the protected product or house mask;
- no clipped house corner, roof edge, logo, glyph or CTA;
- zero text-box overlap and zero overflow;
- minimum final text height 40 px at 1080 px canvas unless the visual manual requires more;
- headline no more than two lines and ten words;
- support no more than two lines and eighteen words;
- CTA one line and two to five words;
- no legal microcopy on the image unless mandatory;
- no gradient by default;
- exact official logo and font assets;
- readable 1080 px, 540 px and 360 px renders;
- OCR text must exactly match intended copy.

### 7. Pass the visual and cross-brand gates

Review the final render, not only source shapes. Require a creative-director PASS for composition, visual hierarchy, product dominance, brand fidelity and conversion focus.

Compare concept, copy and layout against every active brand. Fail if another brand uses the same primary concept, headline formula, narrative sequence, layout archetype or substantially similar text. A color change does not create a different campaign.

### 8. Build and validate the release package

Create `campaign-package.json` according to [references/release-contract.md](references/release-contract.md). Run:

```bash
python scripts/validate_campaign_package.py campaign-package.json --registry <approved-package-directory> --stage creative
```

Do not manually write a PASS or release token. The validator must bind reviews and outputs to artifact hashes.

For publication, require the separate human release secret and run:

```bash
python scripts/validate_campaign_package.py campaign-package.json --registry <approved-package-directory> --stage publish --token-out release-token.json
```

The environment variable `IMPERIAL_RELEASE_HMAC_KEY` must exist only in secret management. Never store or commit it. The publishing adapter must reject missing, invalid or mismatched tokens.

### 9. Audit the published result

After publication, fetch the live ad or post and repeat copy, asset, crop, destination, tracking and visual checks. A post-publication defect must disable or replace the affected item through an approved workflow.

## Fail-closed rules

Immediately set status to `BLOCKED` when:

- a required source or proof is missing;
- a promotion is not explicitly active for that brand and period;
- the concept is generic or interchangeable;
- the copy is not professional direct-response Hungarian;
- a reviewer is also the author;
- a reviewer returns conditional, partial or uncertain approval;
- text overlaps, clips, wraps unexpectedly or covers the product;
- the product image is generic when a typehouse is being sold;
- cross-brand concept, text or layout similarity exceeds the allowed threshold;
- artifact hashes do not match;
- publication lacks a human-signed release token;
- an R6–R7 action is requested without explicit human approval.

Never downgrade these failures to warnings. Never use HTTP 200, file existence, minimum font size, JSON validity or a visually pleasant background image as evidence of marketing quality.

## Delivery

Report:

- selected and rejected concepts with reasons;
- exact source provenance;
- every gate decision and reviewer identity;
- copy and layout similarity results;
- final render checks at all sizes;
- unresolved limitations and required credentials;
- creative-ready versus publication-authorized state.

If any gate fails, deliver the evidence and the blocked status, not a polished explanation of why the artifact is almost acceptable.
