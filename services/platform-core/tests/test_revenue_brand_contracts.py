"""Source-approved brand topics must reach generation without old positioning."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.growth_ops import catalog, processing
from app.growth_ops.canonical_policy import (
    assert_policy_integrity,
    content_focus_for_brand,
    publication_contract_for_brand,
)
from app.growth_ops.revenue_policy import build_brand_source_intent


@pytest.mark.parametrize('brand', ['Property360', 'Venture Studio'])
def test_approved_real_brand_source_problem_matches_current_content_focus(db, brand):
    facts = processing._approved_brand_facts(
        db, brand, current=datetime(2026, 9, 7, 8, tzinfo=UTC),
    )
    intent = build_brand_source_intent(brand, facts)
    source_text = json.dumps(intent, ensure_ascii=False)
    assert processing._matches_brand_focus(source_text, content_focus_for_brand(brand))
    assert intent['brand_id'] == brand
    assert intent['send_allowed'] is False


@pytest.mark.parametrize('brand,wrong_topic', [
    ('Property360', 'Ingatlanüzemeltetés, értékbecslés és befektetés a projekt főajánlata.'),
    ('Venture Studio', 'Vállalkozásfejlesztés, üzletfejlesztés és startup-innováció.'),
])
def test_old_contradictory_topics_no_longer_match_source_brand_focus(brand, wrong_topic):
    assert not processing._matches_brand_focus(wrong_topic, content_focus_for_brand(brand))


def test_venture_generator_and_reviewer_contract_requires_investment_project_evidence():
    contract = publication_contract_for_brand('Venture Studio')
    assert 'ingatlanbefektetési márka' in contract['position']
    assert 'validál' in contract['position']
    assert 'strukturál' in contract['position']
    assert any('kockázat' in requirement for requirement in contract['required'])
    assert any('befektetői meghívás' in requirement for requirement in contract['required'])
    assert any('garantált hozam' in rule for rule in contract['forbidden'])
    assert not any('innovációs helyzet' in requirement for requirement in contract['required'])


def test_property360_focus_agrees_with_existing_contract_and_source_offers():
    focus = content_focus_for_brand('Property360')
    assert processing._matches_brand_focus('A telek és a házterv összehangolása.', focus)
    assert processing._matches_brand_focus('Belsőépítészet a beköltözés előkészítéséhez.', focus)
    contract = publication_contract_for_brand('Property360')
    assert 'ingatlanüzemeltetés' in contract['forbidden']
    assert 'értékbecslés mint főajánlat' in contract['forbidden']
    # The correction must preserve the existing brand list and delivery scope.
    assert_policy_integrity()


def test_baufreund_contract_does_not_promise_unverified_contractual_independence():
    contract = publication_contract_for_brand('BauFreund')
    assert 'független' not in contract['position']
    assert 'barátságos szakmai segítője' in contract['position']


def test_actual_laminate_floor_labor_quote_question_reaches_baufreund_content_focus():
    fixture = Path(__file__).parent / 'fixtures/forum_real_sources/reddit_lakokozosseg.atom'
    _text, candidates = catalog._page_evidence(
        fixture.read_text('utf8'),
        base_url='https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25',
        limit=20000,
    )
    original = next(item for item in candidates if '/1w8rs4c/' in item['url'])
    question = original['label'].split('\n[SOURCE_PAGE_EVIDENCE]', 1)[0]
    assert question.startswith('Munkadíjak?')
    assert 'laminált padló' in question
    assert processing._matches_brand_focus(question, content_focus_for_brand('BauFreund'))
    assert not processing._matches_brand_focus(question, content_focus_for_brand('Venture Studio'))
    assert not processing._matches_brand_focus(question, content_focus_for_brand('Property360'))
