"""Offline synthetic regression tests. No live publication, personal data or leads."""
import hashlib
import hmac
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "services/platform-core/app/growth_ops/revenue_policy.py"
spec = importlib.util.spec_from_file_location("revenue_policy", MODULE)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
NOW = datetime(2026, 9, 6, 13, tzinfo=timezone.utc)
KEY = b"SYNTHETIC-TEST-ONLY-NOT-A-DEPLOYMENT-KEY"


def source(age=1, **changes):
    row = dict(source_url="https://community.example.test/posts/812?utm_source=test", native_id="812",
               text="Kivitelezőt keresek, megvan a telkem, 100 m2 ház. Költségkeretem 60 millió forint.",
               published_at_raw=(NOW - timedelta(hours=age)).isoformat(), observed_at=NOW,
               timestamp_proof="post_published", source_scoped=True, permalink_verified=True)
    row.update(changes)
    return row


def fact(kind="technical", **changes):
    row = dict(id="fact-1", brand_id="TEST-BRAND", kind=kind, public=True,
               statement="A mintaház hasznos alapterülete 100 m².",
               source_url="https://catalogue.example.test/item/verified-model",
               source_sha256="a" * 64, verified_at=(NOW - timedelta(days=1)).isoformat(),
               expires_at=(NOW + timedelta(days=1)).isoformat())
    row.update(changes)
    return row


def registry(rows):
    doc = {"policy": p.POLICY, "facts": rows}
    doc["signature"] = hmac.new(KEY, p._json(doc), hashlib.sha256).hexdigest()
    return doc


def content():
    f = fact()
    capability = fact("capability", id="cap-1", statement="A műszaki egyeztetés kezdeményezhető.", allowed_actions=["request_review"])
    facts = p.verify_fact_registry(registry([f, capability]), key=KEY, now=NOW)
    package = dict(brand_id="TEST-BRAND", content_type="demand_capture",
                   customer_problem="A kiválasztott ház és a telek összeillősége bizonytalan.",
                   buyer_stage="Telekvásárlás előtti döntés", business_goal="Műszaki egyeztetés kezdeményezése",
                   practical_steps=["Ellenőrizze a telek pontos méreteit.", "Vesse össze a beépítési korlátokat a tervvel."],
                   demand_evidence_ids=["demand-1"], title="Telek és ház összhangja",
                   body=f["statement"], facebook_post="Érdemes a telekhez illő házat választani.",
                   claims=[dict(fact_id="fact-1", field="body", text=f["statement"])],
                   cta=dict(label="Küldje el a tervet műszaki egyeztetéshez.", action="request_review", capability_fact_id="cap-1"))
    package["body"] += " " + package["customer_problem"] + " " + " ".join(package["practical_steps"])
    demand = {"demand-1": dict(brand_id="TEST-BRAND", privacy_reviewed=True, excerpt_sha256="b" * 64, verified_at=NOW.isoformat())}
    return package, facts, demand


class IntentTests(unittest.TestCase):
    def test_fresh_buyer_is_hot_not_verified_rich(self):
        result = p.assess_signal(source(), now=NOW)
        self.assertEqual(result["queue"], "HOT")
        self.assertEqual(result["funding_status"], "declared_unverified")
        self.assertFalse(result["contact_allowed"])

    def test_boundaries(self):
        for hours, expected in [(24, "HOT"), (24.01, "WARM"), (72, "WARM"),
                                (72.01, "QUALIFIED_7D"), (168, "QUALIFIED_7D"),
                                (168.01, "CONTENT_SIGNAL"), (720, "CONTENT_SIGNAL"),
                                (720.01, "RESEARCH_ONLY"), (2160, "RESEARCH_ONLY")]:
            with self.subTest(hours=hours):
                self.assertEqual(p.assess_signal(source(hours), now=NOW)["queue"], expected)

    def test_seven_day_signal_needs_strong_intent(self):
        r = p.assess_signal(source(80, text="Kivitelezőt keresek."), now=NOW)
        self.assertFalse(r["lead_eligible"])

    def test_missing_date_is_not_today(self):
        self.assertEqual(p.assess_signal(source(published_at_raw=""), now=NOW)["queue"], "UNVERIFIED")

    def test_unknown_naive_or_future_dates_are_quarantined(self):
        for raw in ["2026-09-06T10:00:00", "ismeretlen", "2027-01-01", (NOW + timedelta(minutes=1)).isoformat()]:
            with self.subTest(raw=raw):
                self.assertEqual(p.assess_signal(source(published_at_raw=raw), now=NOW)["queue"], "UNVERIFIED")

    def test_date_only_retains_conservative_precision(self):
        result = p.assess_signal(source(published_at_raw="2026-09-05"), now=NOW)
        self.assertEqual(result["queue"], "WARM")
        self.assertEqual(result["age_hours_max"], 39)

    def test_relative_hours_and_days(self):
        self.assertEqual(p.assess_signal(source(published_at_raw="2 órája"), now=NOW)["age_hours_max"], 3)
        self.assertEqual(p.assess_signal(source(published_at_raw="1 napja"), now=NOW)["age_hours_max"], 48)

    def test_coarse_months_are_not_recent(self):
        for raw in ["2 hónapja", "egy éve"]:
            self.assertFalse(p.assess_signal(source(published_at_raw=raw), now=NOW)["lead_eligible"])

    def test_old_seen_today_stays_old(self):
        r = p.assess_signal(source(24 * 90), now=NOW)
        self.assertEqual(r["queue"], "RESEARCH_ONLY")

    def test_recheck_uses_now_not_cached_age(self):
        item = source(1)
        r = p.assess_signal(item, now=NOW + timedelta(days=8))
        self.assertEqual(r["queue"], "CONTENT_SIGNAL")

    def test_page_updated_at_not_post_publication(self):
        for kind in ["page_modified", "search_snippet", "discovered_at", "thread_last_reply"]:
            self.assertEqual(p.assess_signal(source(timestamp_proof=kind), now=NOW)["queue"], "UNVERIFIED")

    def test_scope_and_permalink_required(self):
        for overrides in [dict(source_scoped=False), dict(permalink_verified=False), dict(source_url="http://example.test"), dict(observed_at="invalid")]:
            self.assertFalse(p.assess_signal(source(**overrides), now=NOW)["lead_eligible"])

    def test_third_party_bump_does_not_renew(self):
        r = p.assess_signal(source(timestamp_proof="author_renewal", renewal_by_original_author=False), now=NOW)
        self.assertEqual(r["queue"], "UNVERIFIED")

    def test_verified_original_author_renewal(self):
        r = p.assess_signal(source(timestamp_proof="author_renewal", renewal_by_original_author=True), now=NOW)
        self.assertTrue(r["lead_eligible"])

    def test_statement_without_question_mark_is_a_trigger(self):
        r = p.assess_signal(source(text="A kivitelezőm visszamondta. Megvan a telkem, 110 m2 ház."), now=NOW)
        self.assertTrue(r["lead_eligible"])

    def test_general_question_not_sales_lead(self):
        self.assertEqual(p.assess_signal(source(text="Milyen egy Liapor ház?"), now=NOW)["queue"], "CONTENT_SIGNAL")

    def test_closed_or_provider_not_customer(self):
        for txt, queue in [("Már találtam kivitelezőt.", "CLOSED"),
                           ("Kivitelezőt keresek. Tárgytalan!", "CLOSED"),
                           ("Házépítést vállalunk, keressen minket!", "RESEARCH_ONLY")]:
            self.assertEqual(p.assess_signal(source(text=txt), now=NOW)["queue"], queue)

    def test_budget_absence_is_unknown_not_rejected_for_poverty(self):
        r = p.assess_signal(source(text="Kivitelezőt keresek, megvan a telkem."), now=NOW)
        self.assertEqual(r["funding_status"], "unknown")
        self.assertTrue(r["lead_eligible"])

    def test_tracking_dedup_and_native_query_preserved(self):
        self.assertEqual(p.identity("https://e.test/post/1?utm_source=x"), p.identity("https://e.test/post/1?fbclid=y"))
        self.assertNotEqual(p.identity("https://e.test/story.php?story_fbid=1"), p.identity("https://e.test/story.php?story_fbid=2"))
        self.assertNotEqual(p.identity("https://e.test/topic/1#post1"), p.identity("https://e.test/topic/1#post2"))

    def test_cross_day_brand_identity_not_duplicated(self):
        one = p.assess_signal(source(), now=NOW)
        two = p.assess_signal(source(), now=NOW + timedelta(days=1))
        self.assertEqual(one["identity"], two["identity"])
        self.assertEqual(len(p.unique_signals([one, two])), 1)

    def test_today_yesterday_dst(self):
        anchor = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
        start, end = p.observed_window("ma", anchor)
        self.assertEqual(start, datetime(2026, 10, 24, 22, tzinfo=timezone.utc))
        self.assertEqual(end, anchor)


class ContentTests(unittest.TestCase):
    def evaluate(self, package, facts, demand):
        return p.assess_content(package, brand_id="TEST-BRAND", facts=facts, now=NOW, demand_evidence=demand)

    def test_evidence_bound_content_passes_not_auto_publishes(self):
        r = self.evaluate(*content())
        self.assertEqual(r["status"], "PASS")
        self.assertFalse(r["publish_allowed"])

    def test_no_sources_no_filler(self):
        pkg, _, d = content()
        r = self.evaluate(pkg, {}, d)
        self.assertIn("needs_evidence", r["reasons"])

    def test_link_alone_is_not_claim_proof(self):
        pkg, _, d = content()
        pkg["source_urls"] = ["https://catalogue.example.test/item/verified-model"]
        self.assertEqual(self.evaluate(pkg, {}, d)["status"], "BLOCKED")

    def test_wrong_brand_evidence_blocked(self):
        pkg, facts, d = content()
        facts["fact-1"]["brand_id"] = "OTHER-BRAND"
        self.assertEqual(self.evaluate(pkg, facts, d)["status"], "BLOCKED")

    def test_expired_facts_and_capability_blocked(self):
        for key in ["fact-1", "cap-1"]:
            pkg, facts, d = content()
            facts[key]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
            self.assertEqual(self.evaluate(pkg, facts, d)["status"], "BLOCKED")

    def test_invented_price_not_sanitized_into_approval(self):
        pkg, facts, d = content()
        pkg["body"] += " A teljes ház ára 39 900 000 Ft."
        self.assertIn("unbound_numeric_claim:body", self.evaluate(pkg, facts, d)["reasons"])

    def test_numeric_cta_claim_also_checked(self):
        pkg, facts, d = content()
        pkg["cta"]["label"] += " 24 órán belül."
        self.assertIn("unbound_numeric_claim:cta", self.evaluate(pkg, facts, d)["reasons"])

    def test_factual_paraphrase_requires_review(self):
        pkg, facts, d = content()
        pkg["claims"][0]["text"] = "Ez száz négyzetméteres."
        self.assertIn("claim_text_not_bound_to_approved_statement", self.evaluate(pkg, facts, d)["reasons"])

    def test_fake_demand_and_pii_context_rejected(self):
        pkg, facts, d = content()
        self.assertEqual(self.evaluate(pkg, facts, {})["status"], "BLOCKED")
        d["demand-1"]["privacy_reviewed"] = False
        self.assertEqual(self.evaluate(pkg, facts, d)["status"], "BLOCKED")

    def test_proof_cannot_be_fictitious_case(self):
        pkg, facts, d = content()
        pkg["content_type"] = "proof"
        self.assertIn("real_case_study_evidence_required", self.evaluate(pkg, facts, d)["reasons"])

    def test_business_metadata_and_specific_cta_required(self):
        for field in ["customer_problem", "buyer_stage", "business_goal", "content_type", "practical_steps", "cta"]:
            pkg, facts, d = content()
            del pkg[field]
            self.assertEqual(self.evaluate(pkg, facts, d)["status"], "BLOCKED")

    def test_cta_cannot_promise_unapproved_service(self):
        pkg, facts, d = content()
        pkg["cta"]["action"] = "guaranteed_free_site_survey"
        self.assertIn("cta_action_outside_approved_scope", self.evaluate(pkg, facts, d)["reasons"])

    def test_signature_tamper_and_model_verified_flag_fail(self):
        doc = registry([fact()])
        doc["facts"][0]["statement"] = "Kitalált, garantált ár."
        doc["verified"] = True
        with self.assertRaisesRegex(ValueError, "signature_invalid"):
            p.verify_fact_registry(doc, key=KEY, now=NOW)

    def test_price_requires_tax_unit_scope(self):
        self.assertFalse(p.verify_fact_registry(registry([fact("price")]), key=KEY, now=NOW))
        f = fact("price", vat_basis="brutto_5_percent", unit="teljes_haz", scope="verified_spec_v1")
        self.assertIn("fact-1", p.verify_fact_registry(registry([f]), key=KEY, now=NOW))

    def test_private_expired_future_or_unhashed_facts_not_exposed(self):
        for edits in [dict(public=False), dict(expires_at=NOW.isoformat()),
                      dict(verified_at=(NOW + timedelta(days=1)).isoformat()), dict(source_sha256="unknown")]:
            self.assertFalse(p.verify_fact_registry(registry([fact(**edits)]), key=KEY, now=NOW))

    def test_useful_metadata_must_exist_in_published_text(self):
        pkg, facts, d = content()
        pkg["body"] = facts["fact-1"]["statement"]
        reasons = self.evaluate(pkg, facts, d)["reasons"]
        self.assertIn("customer_problem_not_in_public_copy", reasons)
        self.assertIn("practical_steps_not_in_public_copy", reasons)

    def test_registry_wrong_policy_rejected(self):
        doc = {"policy": "old", "facts": [fact()]}
        doc["signature"] = hmac.new(KEY, p._json(doc), hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(ValueError, "policy_mismatch"):
            p.verify_fact_registry(doc, key=KEY, now=NOW)

    def test_duplicate_fact_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            p.verify_fact_registry(registry([fact(), fact()]), key=KEY, now=NOW)

    def test_short_key_rejected(self):
        with self.assertRaisesRegex(ValueError, "key_too_short"):
            p.verify_fact_registry(registry([fact()]), key=b"bad", now=NOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
