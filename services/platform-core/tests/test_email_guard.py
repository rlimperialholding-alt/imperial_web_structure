"""ReDoS-mentes e-mail validáció tesztjei (adversarial hosszúságú inputokkal)."""

from __future__ import annotations

import time

import pytest

from app.services.email_guard import is_valid_email
from app.services.tender_mail import normalize_email


class TestValidEmails:
    @pytest.mark.parametrize(
        "email",
        [
            "partner@example.com",
            "Pm@Imperial.local",
            "first.last+tag@example.co.uk",
            "a@b.hu",
            "ügyfél@example.hu",
            '"user"@example.com',
            "user@123.123",
            "user@münchen.de",
        ],
    )
    def test_accepted(self, email: str) -> None:
        assert is_valid_email(email)

    def test_normalize_email_lowercases(self) -> None:
        assert normalize_email("  PM@Example.COM ") == "pm@example.com"


class TestInvalidEmails:
    @pytest.mark.parametrize(
        "email",
        [
            "",
            "not-an-email",
            "@example.com",
            "user@",
            "user@@example.com",
            "user name@example.com",
            "user@exa mple.com",
            "user@-example.com",
            "user@example-.com",
            "user@example",
            "user@example.c",
            "user@exa..mple.com",
            ".user@example.com",
            "user.@example.com",
            "us..er@example.com",
            "user@127.0.0.1",
            "user@example.com\nBcc: victim@example.com",
            None,
            42,
        ],
    )
    def test_rejected(self, email: object) -> None:
        assert not is_valid_email(email)

    def test_tender_mail_normalize_rejects(self) -> None:
        with pytest.raises(ValueError):
            normalize_email("user@@example.com")


class TestBusinessEmailSubsetEdgeCases:
    """Az elfogadott üzleti email-részhalmaz dokumentált peremeselei.

    A döntések a korábbi üzleti szerződést (tender_portal, tender_mail,
    partner_control, imperial_care közös ``[^@\s]+@[^@\s]+\.[^@\s]+``
    validációja) követik; lásd az ``app/services/email_guard.py`` modul
    docstringjét. Biztonsági validáció nem lazult.
    """

    def test_quoted_local_part_without_spaces_is_accepted(self) -> None:
        # Az idézett local part a régi üzleti szerződésben érvényes volt.
        assert is_valid_email('"user"@example.com')

    def test_quoted_local_part_with_space_is_rejected(self) -> None:
        # A szóköz soha nem volt megengedett (header-injekciós felület).
        assert not is_valid_email('"john doe"@example.com')

    def test_numeric_tld_is_accepted(self) -> None:
        # A numerikus TLD a régi üzleti szerződésben érvényes volt.
        assert is_valid_email("user@123.123")

    def test_single_label_domain_is_rejected(self) -> None:
        # Single-label domain sem a régi, sem az új szerződésben nem érvényes.
        assert not is_valid_email("user@localhost")

    def test_single_character_tld_is_rejected(self) -> None:
        assert not is_valid_email("user@example.c")

    def test_ip_literal_domain_is_rejected(self) -> None:
        # 127.0.0.1: az utolsó label egykarakteres, ezért elutasított.
        assert not is_valid_email("user@127.0.0.1")

    def test_internationalized_domain_is_accepted(self) -> None:
        assert is_valid_email("user@münchen.de")


class TestAdversarialLength:
    def test_documented_input_limit_254(self) -> None:
        assert not is_valid_email("a" * 64 + "@" + "b" * 63 + ".hu" + "x" * 200)
        assert is_valid_email("a@example.com")

    def test_long_repetitive_bang_string_stays_fast_and_rejected(self) -> None:
        # A korábbi [^@\s]+@[^@\s]+\.[^@\s]+ minta itt polinomiális visszalépést
        # okozott. A lineáris validátornak azonnal el kell utasítania.
        for payload in ("!" * 5_000, "!" * 50_000, "!" * 100_000):
            started = time.perf_counter()
            assert not is_valid_email(payload + "@example.com")
            elapsed = time.perf_counter() - started
            assert elapsed < 0.5, f"Lineáris validálás várt, mért: {elapsed:.3f}s"

    def test_many_at_signs_rejected_quickly(self) -> None:
        payload = "@".join(["a"] * 10_000)
        started = time.perf_counter()
        assert not is_valid_email(payload)
        assert time.perf_counter() - started < 0.5
