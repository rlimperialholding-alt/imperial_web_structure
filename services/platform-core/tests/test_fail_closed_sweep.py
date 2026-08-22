"""Fail-closed paraméter-sweep a fő UI/API POST-kezelőkre.

A tábla a main.py POST-kezelőinek jogosultsági és hiányzó-entitás
fail-closed ágait rögzíti determinisztikus, szintetikus, hálózatmentes
sorokkal: minden sor egy valós üzleti elutasítási szerződés (rossz
szerepkör, hiányzó rekord, érvénytelen bemenet, hiányzó token), az
elvárt HTTP-státusz explicit. A sorok a kalibrált tényleges
viselkedést pinelik; 5xx-et egyetlen sor sem enged meg.
"""

from __future__ import annotations

import json
import os


def _load_rows():
    path = os.path.join(os.path.dirname(__file__), "fail_closed_rows.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return [row for group in raw for row in group]


def test_fail_closed_route_sweep(client):
    """Minden sor: bejelentkezés (cache-elt session), kérés, pinelt státusz."""
    payload = {
        "reason": "Szintetikus fail-closed indoklás.",
        "evidence": "Szintetikus fail-closed bizonyíték.",
        "title": "Szintetikus cím",
        "name": "Szintetikus név",
        "decision": "rejected",
        "status": "pass",
        "note": "Szintetikus megjegyzés.",
        "objective": "Szintetikus cél.",
        "idempotency_key": "sweep-key-1",
        "csrf_token": "",
        "row_version": "1",
        "project_id": "PRJ-SWEEP-X",
    }
    sessions = {}
    for row in _load_rows():
        method, route, role, expected = row[0], row[1], row[2], row[3]
        with_payload = len(row) > 4
        if role is None:
            client.cookies.clear()
        elif role in sessions:
            client.cookies.clear()
            client.cookies.update(sessions[role])
        else:
            client.cookies.clear()
            response = client.post(
                "/login",
                data={"email": role, "password": "Imperial2026!"},
                follow_redirects=False,
            )
            assert response.status_code == 303, f"login failed for {role}"
            sessions[role] = dict(client.cookies.items())
        if method == "POST":
            data = payload if with_payload else {}
            response = client.post(route, data=data, follow_redirects=False)
        else:
            response = client.get(route, follow_redirects=False)
        assert response.status_code == expected, (
            f"{role or chr(39) + chr(39)} {method} {route}: "
            f"expected {expected}, got {response.status_code}"
        )
