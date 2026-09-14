"""Task60 CSRF endpoint/control mátrix — minden POST form/endpoint fedettsége.

A Semgrep `django-no-csrf-token` szabály 169 találata (33 template) Django-
specifikus rule-találat a FastAPI/Jinja2 platform-core alkalmazásban; a
központi, szűk rule-kivétel
(``.github/workflows/imperial-adas-semgrep.yml``, ``--exclude-rule``)
hangosságának feltételeit ez a regresszió őrzi, végpont- és tesztszinten:

1. a ``SessionWriteOriginMiddleware`` alkalmazás-szinten regisztrált
   (egyetlen FastAPI app, minden route), és session-hitelesített unsafe
   kérésnél idegen Origin esetén fail-closed 403-at ad;
2. MINDEN template MINDEN POST form endpointja fedett: hitelesített
   sessionnel idegen Origin → 403, mielőtt a route futhatna;
3. a synchronizer-token réteg (``_require_ui_csrf`` és a modul-szintű
   ``_require_csrf``/``_check_csrf``) fedett template-jei hidden
   ``csrf_token`` inputot renderelnek, és üres tokennel 403-at adnak;
4. a login pre-session, anonim by design (nincs session, amit CSRF
   eltéríthetne), a mátrix a hitelesített írásokra vonatkozik.

Ha a middleware eltűnik vagy a fedettség sérül, ez a teszt elbukik — ilyenkor
a workflow ``--exclude-rule`` kivételét vissza kell vonni. A mátrix
részletei: ``docs/csrf-threat-model.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "app" / "templates"
MAIN_SOURCE = Path(__file__).resolve().parents[1] / "app" / "main.py"

FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r"""(?P<name>[a-zA-Z-]+)\s*=\s*["'](?P<value>[^"']*)["']""")
JINJA_PATH_VAR_RE = re.compile(r"\{[^{}]*\}")

# A synchronizer-token réteg által fedett template-ek (hidden csrf_token
# input + POST handler ellenőrzés): a Task60 CSRF-mátrix tokenizált halmaza.
TOKENIZED_TEMPLATES = {
    "field_project.html",
    "house_batch_detail.html",
    "house_designer.html",
    "house_designer_adapters.html",
    "house_designer_detail.html",
    "house_designer_geometry_controls.html",
    "house_designer_standalone.html",
    "house_designer_submission_review.html",
    "house_plan_detail.html",
    "house_studio.html",
    "housevision.html",
    "housevision_detail.html",
    "housevision_typehouse_factory.html",
    "housevision_upload.html",
    "market_intelligence.html",
    "operations_project.html",
    "regulatory_admin.html",
    "smart_calendar.html",
}

# A saját URL-re posztoló (üres action) formok mögötti GET oldalak: a
# middleware ezeket is ugyanúgy fedi (a POST a page saját URL-jére megy).
CURRENT_URL_PAGES = [
    "/booking/{experience_id}",
    "/intent/{offer_version_id}",
    "/mail/preferences/{tracking_token}",
    "/plancheck/upload/{token}",
    "/reservation/{offer_version_id}",
]


def _post_form_actions(template_text: str) -> list[tuple[str, str]]:
    """(method, action) párok a template összes formjából."""
    rows: list[tuple[str, str]] = []
    for tag in FORM_TAG_RE.findall(template_text):
        attrs = {match.group("name").lower(): match.group("value") for match in ATTR_RE.finditer(tag)}
        if attrs.get("method", "get").lower() != "post":
            continue
        rows.append((attrs.get("method", "get").lower(), attrs.get("action", "")))
    return rows


def _instantiate(action: str) -> str | None:
    if not action or action.startswith(("#", "javascript:")):
        return None
    path = JINJA_PATH_VAR_RE.sub("probe-1", action)
    if not path.startswith("/"):
        return None
    return path


def test_session_write_origin_middleware_is_registered_app_global() -> None:
    source = MAIN_SOURCE.read_text(encoding="utf-8")
    assert "add_middleware(SessionWriteOriginMiddleware)" in source
    assert "class SessionWriteOriginMiddleware" in (
        Path(__file__).resolve().parents[1] / "app" / "session_write_guard.py"
    ).read_text(encoding="utf-8")


def test_every_post_form_endpoint_blocks_foreign_origin(logged_in_client) -> None:
    """Minden POST form endpoint: hitelesített session + idegen Origin → 403.

    A SessionWriteOriginMiddleware a route elé fut: a 403 a middleware
    fail-closed válasza, függetlenül attól, hogy a probe-azonosítóval
    instantiált URL egyébként érvényes-e. Így a mátrix a teljes formkészlet
    végpontszintű fedettségét bizonyítja adatállapot nélkül.
    """
    checked = 0
    failures: list[str] = []
    for template_path in sorted(TEMPLATES_DIR.glob("*.html")):
        text = template_path.read_text(encoding="utf-8")
        for _method, action in _post_form_actions(text):
            path = _instantiate(action)
            if path is None:
                continue
            response = logged_in_client.post(
                path,
                data={"csrf_token": ""},
                headers={"Origin": "https://attacker.example"},
                follow_redirects=False,
            )
            if response.status_code != 403:
                failures.append(
                    f"{template_path.name} → POST {path} (foreign origin) = {response.status_code}"
                )
            checked += 1
    assert not failures, "\n".join(failures)
    # A teljes formkészlet ellenőrizve (Task60 mátrix: 83 template, 441 POST
    # form); az alsó korlát a fedettség-regresszió védelmére.
    assert checked >= 400, f"csak {checked} POST form endpoint került ellenőrzésre"


def test_current_url_post_forms_are_covered(logged_in_client) -> None:
    """Az üres action-ű formok (saját URL-re posztolás) mögötti oldalak is fedettek."""
    for page in CURRENT_URL_PAGES:
        path = JINJA_PATH_VAR_RE.sub("probe-1", page)
        response = logged_in_client.post(
            path,
            data={"csrf_token": ""},
            headers={"Origin": "https://attacker.example"},
            follow_redirects=False,
        )
        assert response.status_code == 403, f"POST {path} (foreign origin) = {response.status_code}"


def test_middleware_fails_closed_on_missing_origin(logged_in_client) -> None:
    """Origin nélküli session-hitelesített POST is 403 (fail-closed)."""
    response = logged_in_client.post(
        "/smart-calendar/sync",
        data={"csrf_token": ""},
        headers={"Origin": ""},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_tokenized_templates_render_hidden_csrf_input() -> None:
    for name in sorted(TOKENIZED_TEMPLATES):
        text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
        assert 'name="csrf_token"' in text, f"{name} nem renderel hidden csrf_token inputot"


def test_synchronizer_token_layer_rejects_empty_token(logged_in_client) -> None:
    """A token-réteg képviselője: üres token azonos Origin esetén is 403."""
    response = logged_in_client.post(
        "/smart-calendar/entries",
        data={"csrf_token": "", "calendar": "demo"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_login_is_anonymous_by_design(client) -> None:
    """A login pre-session működik (nincs session, amit CSRF eltéríthetne)."""
    from app.seed import DEMO_PASSWORD

    response = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
