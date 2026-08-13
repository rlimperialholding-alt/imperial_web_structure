#!/usr/bin/env python3
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "data" / "claim-evidence.json").read_text(encoding="utf-8"))
TODAY = dt.date.today()

errors = []
sources = DATA.get("sources", {})
bindings = DATA.get("route_bindings", {})
required_routes = {
    "/szamolok/teljes-projektkeret",
    "/szamolok/utemterv",
    "/szamolok/energia-es-koltseg",
    "/muszaki-adatok",
    "/mibol-epuljon",
    "/technologiak/favazas",
    "/technologiak/tegla",
    "/technologiak/liapor",
    "/technologiak/acelszerkezet",
}

for route in sorted(required_routes):
    ids = bindings.get(route, [])
    if not ids:
        errors.append(f"Nincs forrásazonosító a számszerű állításokat tartalmazó útvonalhoz: {route}")
    for source_id in ids:
        if source_id not in sources:
            errors.append(f"Ismeretlen forrásazonosító: {route} -> {source_id}")

for source_id, source in sources.items():
    for field in ("kind", "title", "source", "valid_from", "valid_until", "review_state", "rules"):
        if not source.get(field):
            errors.append(f"Hiányzó {field}: {source_id}")
    try:
        valid_from = dt.date.fromisoformat(source["valid_from"])
        valid_until = dt.date.fromisoformat(source["valid_until"])
        if valid_until < valid_from:
            errors.append(f"Fordított érvényesség: {source_id}")
        if TODAY > valid_until:
            errors.append(f"Lejárt állításforrás: {source_id} ({valid_until})")
    except (KeyError, ValueError):
        errors.append(f"Hibás érvényességi dátum: {source_id}")

if DATA.get("publication_allowed") is not False:
    errors.append("A staging állításjegyzék nem engedélyezhet publikálást.")

if errors:
    raise SystemExit("\n".join(errors))

print(f"Állításforrás-kapu rendben: {len(bindings)} útvonal, {len(sources)} forrás; publikálás továbbra is blokkolt.")
