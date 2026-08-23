"""Email üzleti contract paritásteszt: contract generator vs. központi guard.

A contract generator saját ``_valid_email`` validátora és a központi
``app.services.email_guard.is_valid_email`` ugyanazt a dokumentált üzleti
részhalmazt fogadja el (idézett local part, numerikus TLD), és ugyanazokat
az eseteket utasítja el fail-closed módon (single-label domain, egykarakteres
TLD, szóköz, érvénytelen cím). Mindkét validátor reguláris kifejezés nélküli,
lineáris bejárást használ, ezért ReDoS-mentes.

A csomaghatár (a contract generator önálló, python-docx-only csomag) nem
engedi a közös importot, ezért a paritást ez a közös contractteszt rögzíti:
a két implementációnak azonos bemeneten azonos döntést kell adnia.
"""

from __future__ import annotations

import time

import pytest

from app.services.email_guard import is_valid_email
from integrations.contract_generator_v0_4.imperial_contract_generator.core import (
    _valid_email,
)

# A 18-as repo-contract által dokumentáltan elfogadott üzleti részhalmaz.
BUSINESS_ACCEPTED = [
    "partner@example.com",
    "Pm@Imperial.local",
    "first.last+tag@example.co.uk",
    "a@b.hu",
    "ügyfél@example.hu",
    '"user"@example.com',
    "user@123.123",
    "user@münchen.de",
    "o'hara@example.com",
]

# A dokumentált szerződés szerint elutasított, fail-closed esetek.
BUSINESS_REJECTED = [
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
    "user@localhost",
    "user@example.c",
    "user@exa..mple.com",
    ".user@example.com",
    "user.@example.com",
    "us..er@example.com",
    "user@127.0.0.1",
    "user@example.com\nBcc: victim@example.com",
    '"john doe"@example.com',
]

# Teljes paritásmátrix: a két validátornak minden esetben azonos döntést kell
# adnia; a mátrix a közös hossz-/label-/karakterkészlet-szabályok határait is
# rögzíti.
PARITY_CASES: dict[str, bool] = {
    **{case: True for case in BUSINESS_ACCEPTED},
    **{case: False for case in BUSINESS_REJECTED},
    # Határesetek: hossz- és label-korlátok.
    "user@example.com.": True,  # záró pont a domain végén mindkettőnél rstrip
    "user@sub1.example.com": True,  # numerikus belső label
    "user@example.co": True,  # kétkarakteres TLD
    "a" * 64 + "@example.com": True,  # 64 karakteres local part (határon)
    "user@" + "b" * 63 + ".hu": True,  # 63 karakteres label (határon)
    "a" * 65 + "@example.com": False,  # 65 karakteres local part (túllépés)
    "user@" + "b" * 64 + ".hu": False,  # 64 karakteres label (túllépés)
    "a" * 64 + "@" + "b" * 63 + ".hu" + "x" * 200: False,  # teljes hossz > 254
    "us" + chr(0) + "er@example.com": False,  # control karakter a local partban
    None: False,
    42: False,
}


@pytest.mark.parametrize("email", BUSINESS_ACCEPTED)
def test_contract_generator_accepts_documented_business_subset(email: str) -> None:
    assert _valid_email(email)


@pytest.mark.parametrize("email", BUSINESS_ACCEPTED)
def test_email_guard_accepts_documented_business_subset(email: str) -> None:
    assert is_valid_email(email)


@pytest.mark.parametrize("email", BUSINESS_REJECTED)
def test_contract_generator_rejects_fail_closed_cases(email: str) -> None:
    assert not _valid_email(email)


@pytest.mark.parametrize("email", BUSINESS_REJECTED)
def test_email_guard_rejects_fail_closed_cases(email: str) -> None:
    assert not is_valid_email(email)


@pytest.mark.parametrize("case", list(PARITY_CASES))
def test_both_validators_agree_on_shared_contract_matrix(case: object) -> None:
    expected = PARITY_CASES[case]
    assert _valid_email(case) is expected
    assert is_valid_email(case) is expected


class TestAdversarialLengthParity:
    def test_long_repetitive_input_stays_linear_and_rejected_in_both(self) -> None:
        # A korábbi regexes korszakban az ilyen input polinomiális visszalépést
        # okozott; mindkét lineáris validátornak azonnal el kell utasítania.
        for payload in ("!" * 5_000, "!" * 50_000, "!" * 100_000):
            started = time.perf_counter()
            assert not _valid_email(payload + "@example.com")
            assert not is_valid_email(payload + "@example.com")
            elapsed = time.perf_counter() - started
            assert elapsed < 0.5, f"Lineáris validálás várt, mért: {elapsed:.3f}s"

    def test_many_at_signs_rejected_quickly_in_both(self) -> None:
        payload = "@".join(["a"] * 10_000)
        started = time.perf_counter()
        assert not _valid_email(payload)
        assert not is_valid_email(payload)
        assert time.perf_counter() - started < 0.5
