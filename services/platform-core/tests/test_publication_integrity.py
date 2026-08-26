from __future__ import annotations

import unittest

from app.growth_ops.publication_integrity import (
    PublicationIntegrityError,
    PublicationObservation,
    evaluate_daily_publication_integrity,
    generate_brand_isolated,
    is_exact_post_permalink,
    validate_content_package,
    validate_question_permalink,
)


class PermalinkTests(unittest.TestCase):
    def test_rejects_listing_and_search_urls(self):
        bad = (
            "https://example.hu/",
            "https://example.hu/blog/",
            "https://example.hu/search?q=hazepites",
            "https://example.hu/forum/topics/",
            "http://example.hu/2026/08/konkret-kerdes",
        )
        self.assertTrue(all(not is_exact_post_permalink(url) for url in bad))

    def test_accepts_specific_https_post(self):
        self.assertTrue(
            is_exact_post_permalink(
                "https://example.hu/2026/08/hogyan-valasszak-kivitelezot"
            )
        )

    def test_listing_candidate_must_be_literal_and_same_site(self):
        candidate = "https://forum.example.hu/tema/konkret-hazepitesi-kerdes-123"
        source = f'<a href="{candidate}">Kérdés</a>'
        self.assertEqual(
            validate_question_permalink(
                route_url="https://forum.example.hu/friss-temak",
                candidate_url=candidate,
                source_text=source,
            ),
            candidate,
        )
        with self.assertRaises(PublicationIntegrityError):
            validate_question_permalink(
                route_url="https://forum.example.hu/friss-temak",
                candidate_url="https://other.example.com/post/12345678",
                source_text=source,
            )

    def test_relative_permalink_is_resolved_and_must_be_observed(self):
        route = "https://forum.example.hu/friss-temak"
        relative = "/tema/konkret-hazepitesi-kerdes-123"
        source = f'<a href="{relative}">Kérdés</a>'
        self.assertEqual(
            validate_question_permalink(
                route_url=route, candidate_url=relative, source_text=source
            ),
            "https://forum.example.hu/tema/konkret-hazepitesi-kerdes-123",
        )


class ContentIsolationTests(unittest.TestCase):
    def test_unsupplied_source_is_rejected(self):
        with self.assertRaises(PublicationIntegrityError):
            validate_content_package(
                {
                    "brand_id": "Prefab",
                    "title": "Hasznos építési ellenőrzőlista",
                    "format": "article",
                    "body": "x" * 500,
                    "source_urls": ["https://untrusted.example/post/12345678"],
                },
                expected_brand="Prefab",
                allowed_urls={"https://trusted.example/post/12345678"},
            )

    def test_one_brand_failure_does_not_block_other_brand(self):
        def generator(brand: str, attempt: int):
            if brand == "Broken":
                return {"brand_id": brand, "title": "bad"}, "req-bad"
            return {
                "brand_id": brand,
                "title": "Hasznos szakmai napi tartalom",
                "format": "article",
                "body": "Megbízható, ellenőrizhető szakmai szöveg. " * 20,
                "source_urls": [],
            }, "req-ok"

        broken = generate_brand_isolated(
            brand_id="Broken", allowed_urls=set(), generator=generator, max_attempts=3
        )
        good = generate_brand_isolated(
            brand_id="Prefab", allowed_urls=set(), generator=generator, max_attempts=3
        )
        self.assertEqual(broken.status, "failed")
        self.assertEqual(broken.attempts, 3)
        self.assertEqual(good.status, "quarantined")
        self.assertEqual(good.attempts, 1)


class DailyGateTests(unittest.TestCase):
    def test_18_of_19_can_never_be_healthy(self):
        expected = {f"Brand-{i}": ["wordpress"] for i in range(19)}
        rows = [
            PublicationObservation(
                brand_id=f"Brand-{i}",
                channel="wordpress",
                state="READBACK_VERIFIED",
                public_url=f"https://brand-{i}.example/post/12345678",
                proof_id=f"proof-{i}",
                image_verified=True,
            )
            for i in range(18)
        ]
        result = evaluate_daily_publication_integrity(
            expected_routes=expected, observations=rows
        )
        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.verified, 18)
        self.assertEqual(result.expected, 19)

    def test_missing_image_blocks_green_status(self):
        result = evaluate_daily_publication_integrity(
            expected_routes={"Prefab": ["wordpress", "facebook"]},
            observations=[
                PublicationObservation(
                    "Prefab",
                    "wordpress",
                    "READBACK_VERIFIED",
                    "https://prefab.example/post/12345678",
                    "proof-web",
                    True,
                ),
                PublicationObservation(
                    "Prefab",
                    "facebook",
                    "READBACK_VERIFIED",
                    "https://facebook.example/post/12345678",
                    "proof-fb",
                    False,
                ),
            ],
        )
        self.assertEqual(result.status, "degraded")
        self.assertIn("Prefab/facebook:image_not_verified", result.invalid)


    def test_duplicate_observation_blocks_green_status(self):
        rows = [
            PublicationObservation(
                "Prefab", "wordpress", "READBACK_VERIFIED",
                "https://prefab.example/post/12345678", "proof-1", True
            ),
            PublicationObservation(
                "Prefab", "wordpress", "READBACK_VERIFIED",
                "https://prefab.example/post/12345678", "proof-2", True
            ),
        ]
        result = evaluate_daily_publication_integrity(
            expected_routes={"Prefab": ["wordpress"]}, observations=rows
        )
        self.assertEqual(result.status, "degraded")
        self.assertIn("Prefab/wordpress:duplicate_observation", result.invalid)

    def test_all_verified_is_healthy(self):
        result = evaluate_daily_publication_integrity(
            expected_routes={"Prefab": ["wordpress", "facebook"]},
            observations=[
                PublicationObservation(
                    "Prefab",
                    "wordpress",
                    "READBACK_VERIFIED",
                    "https://prefab.example/post/12345678",
                    "proof-web",
                    True,
                ),
                PublicationObservation(
                    "Prefab",
                    "facebook",
                    "READBACK_VERIFIED",
                    "https://facebook.example/post/12345678",
                    "proof-fb",
                    True,
                ),
            ],
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.verified, 2)


if __name__ == "__main__":
    unittest.main()
