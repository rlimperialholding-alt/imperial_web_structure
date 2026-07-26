from app.process_cards.domain import RealRole
from scripts.credential_manifest import build_manifest


def test_manifest_contains_exactly_five_human_roles_and_unique_tokens():
    manifest = build_manifest()
    tokens = manifest["generated_secrets"]["HUMAN_ROLE_TOKENS_JSON"]
    assert set(tokens) == {role.value for role in RealRole}
    values = list(tokens.values())
    assert len(values) == len(set(values)) == 5
    assert all(len(value) >= 32 for value in values)
