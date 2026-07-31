# Release contract

Create one `campaign-package.json` per final creative or coherent carousel.

## Required top-level fields

- `schema_version`: `1.0`
- `brand_id`, `campaign_id`, `campaign_type`, `period`
- `author_id`
- `source_hashes`
- `strategy`
- `copy`
- `visual`
- `program_context`
- `artifacts`
- `reviews`
- `release`

## Required strategy fields

- `concept_id`
- `target_segment`
- `life_situation`
- `market_problem`
- `fear_or_tension`
- `desired_outcome`
- `product_or_service`
- `primary_offer`
- `brand_specific_mechanism`
- `brand_specific_differentiator`
- `proof_stack` with at least two items
- `objection_answer`
- `why_now`
- `conversion_event`
- `primary_concept_class`

## Required copy fields

- `headline`, `support`, `cta`, `primary_text`
- `concept_candidates` with at least three entries
- `rejected_candidates` with at least two entries and reasons

## Required visual fields

- `canonical_master`, `render_1080`
- `layout_archetype`
- `photo_visible_ratio` at least `0.75`
- `min_text_px` at least `40`
- `headline_lines` no more than `2`
- `support_lines` no more than `2`
- `cta_lines` exactly `1`
- `subject_mask`
- `text_subject_intersections` equal to `0`
- `text_box_overflows` equal to `0`
- `ocr_match`, `downscale_readable`, `official_brand_assets` equal to `true`
- `gradient_used` equal to `false` unless explicitly approved
- `typehouse_image_verified` equal to `true` for a typehouse campaign

## Program context

- `residential_house_brand`
- `product_led_share`
- `cross_brand_registry`
- `concept_unique`, `layout_unique` equal to `true`
- `allowed_copy_similarity` no greater than the configured threshold

## Artifacts and reviews

Each artifact entry contains `path`, `sha256` and one of the required `role` values:
`copy`, `visual_source`, `canonical_master`, `render_1080`, `subject_mask` or
`platform_export`. The validator recalculates the hash and derives one
`artifact_set_sha256`.

Require PASS reviews for:

- `marketing_strategist`
- `direct_response_copywriter`
- `hungarian_language_editor`
- `brand_guardian`
- `creative_director`
- `legal`
- `financial`

Every review contains `role`, `reviewer_id`, `decision`, and the same `artifact_set_sha256`. Critical creative reviewers must be distinct from the author and from one another.

## Release

Use:

- `publication_authorized: false` during local production;
- `r6_r7: HUMAN_ONLY` always;
- a human approval object only at publication stage.

Publication requires `IMPERIAL_RELEASE_HMAC_KEY`. The validator writes a hash-bound HMAC token. Do not commit the secret or reuse a token after any artifact changes.
