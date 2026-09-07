"""Bounded public-source smoke check against the installed application code.

Run inside the application image: python /tmp/verify_radar_server_sources.py
--app-root /app. No model, database session, message, or publishing call is made.
Only the four fixed public GET targets below are read, plus their bounded
anonymous redirects. This checks source transport, parsing and revenue policy;
it does not claim to test the scheduler, model extraction or database retention.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PH_TOPIC = (
    "https://prohardver.hu/tema/"
    "lakasfelujito_szerelo_szakemberkereso_nagy_topic_viz_gaz_villany_futes_festes_burkolas_stb"
)
SOURCES = {
    "reddit_new": "https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25",
    "index_post": "https://forum.index.hu/Article/viewArticle?a=172270043&t=9004917",
    "prohardver_post": PH_TOPIC + "/hsz_171759-171759.html",
    "ddg_discovery": "https://lite.duckduckgo.com/lite/?q=felujitas+forum",
}


def _safe_excerpt(value: str) -> str:
    """Omit author fields; redact explicit handles and contact details in body."""
    text = value.partition("[SOURCE_PAGE_EVIDENCE]")[0]
    text = re.sub(r"https?://\S+", "[link]", text)
    text = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+", "[email]", text)
    text = re.sub(r"(?<!\w)(?:/?u/|@)[\w.-]+", "[felhasználó]", text)
    text = re.sub(r"(?<!\w)(?:\+36|06)[ -]?(?:\d[ -]?){8,9}\b", "[telefon]", text)
    return " ".join(text.split())[:260]


def _worker(key: str, app_root: Path) -> dict:
    # Set before imports: even application engine construction uses only a fresh
    # in-memory SQLite URL. A connection listener below rejects *all* DB access.
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["ENVIRONMENT"] = "test"
    sys.path.insert(0, str(app_root))
    from app.database import engine
    from app.growth_ops import catalog, processing, revenue_policy
    from sqlalchemy import event

    def deny_database(*args, **kwargs):
        raise RuntimeError("database_connection_forbidden_in_source_smoke")

    event.listen(engine, "do_connect", deny_database)
    started = time.monotonic()
    url = SOURCES[key]
    result = {
        "source": key,
        "url": url,
        "observed_at": datetime.now(UTC).isoformat(),
        "fetch_callable": "app.growth_ops.catalog._forum_page_get",
        "parser_callable": "app.growth_ops.catalog._page_evidence",
        "policy_callable": "processing._question_freshness -> revenue_policy.assess_signal",
        "policy_version": revenue_policy.POLICY,
        "database_access": False,
    }
    try:
        response = catalog._forum_page_get(url, timeout_seconds=15, max_response_bytes=2_000_000)
        body = bytes(response.get("body") or b"")
        result.update(
            http_status=response.get("status_code"),
            final_url=response.get("final_url", url),
            redirect_count=response.get("redirect_count", 0),
            source_ip=response.get("source_ip"),
            content_bytes=len(body),
            content_sha256=hashlib.sha256(body).hexdigest(),
        )
        if not 200 <= int(response["status_code"]) < 300:
            result.update(status="source_unavailable", reason="non_success_http_status")
            return result
        text = catalog._forum_decode_body(response)
        _visible, links = catalog._page_evidence(text, base_url=url, limit=60_000)
        # Search labels are discovery only. Never apply their dates/text as post evidence.
        if key == "ddg_discovery":
            unique = {item["url"]: item for item in links}
            result.update(
                status="discovery_candidates_found" if unique else "no_discovery_candidates",
                candidate_count=len(links),
                unique_candidate_count=len(unique),
                candidates=[
                    {"url": item["url"], "label": _safe_excerpt(item["label"]),
                     "original_date": None, "bucket": "DISCOVERY_ONLY"}
                    for item in list(unique.values())[:12]
                ],
                note="Candidate pages are not fetched here; search dates never prove original post dates.",
            )
            return result
        # An exact URL must match its own original message, not a nearby quote.
        if key in {"index_post", "prohardver_post"}:
            links = [item for item in links if catalog._same_forum_post(item["url"], url)]
        observed = datetime.now(UTC)
        decisions = []
        seen = set()
        for item in links:
            source_url = item["url"]
            if source_url in seen:
                continue
            seen.add(source_url)
            label = item["label"]
            source_text = label.partition("[SOURCE_PAGE_EVIDENCE]")[0].strip()
            relevant = processing._useful_forum_question(source_text) or revenue_policy.is_purchase_signal(source_text)
            metadata = processing._source_page_metadata_from_label(label)
            freshness = processing._question_freshness(
                {**metadata, "source_url": source_url, "question": source_text},
                evidence_text=label, observed_at=observed, require_source_date_proof=True,
            )
            decision = freshness["revenue_decision"]
            decisions.append({
                "url": source_url,
                "relevant": relevant,
                "snippet": _safe_excerpt(source_text) if relevant else "[nem releváns poszt; szöveg kihagyva]",
                "original_date_raw": freshness["published_at_raw"],
                "original_date": freshness["published_at"].isoformat() if freshness["published_at"] else None,
                "date_source": freshness["published_at_source"],
                "bucket": freshness["freshness_decision"],
                "intent_score": decision["intent_score"],
                "lead_eligible": bool(relevant and decision["lead_eligible"]),
                "contact_allowed": decision["contact_allowed"],
                "reasons": freshness["reasons"],
            })
        relevant_decisions = [item for item in decisions if item["relevant"]]
        queues = {}
        for item in relevant_decisions:
            queues[item["bucket"]] = queues.get(item["bucket"], 0) + 1
        result.update(
            status="source_evidence_parsed" if decisions else "no_original_post_evidence",
            original_post_count=len(decisions),
            relevant_count=len(relevant_decisions),
            verified_original_dates=sum(bool(item["original_date"]) for item in decisions),
            relevant_queues=queues,
            decisions=(relevant_decisions + [item for item in decisions if not item["relevant"]])[:25],
        )
    except Exception as exc:  # noqa: BLE001 - report only exception type, never configuration values
        # No raw exception/repr: configuration errors can include environment values.
        result.update(status="failed", error_type=type(exc).__name__)
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=Path("/app"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=tuple(SOURCES), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(_worker(args.worker, args.app_root), ensure_ascii=False))
        return
    started = time.monotonic()
    deadline = started + 89.0
    report = {
        "verified_at": datetime.now(UTC).isoformat(),
        "mode": "real_public_source_smoke",
        "app_root": str(args.app_root.resolve()),
        "total_timeout_seconds": 90,
        "source_limit": len(SOURCES),
        "external_send_or_publication": False,
        "model_called": False,
        "database_used": False,
        "isolation": "separate sequential processes; SQLite memory URL; database connections rejected",
        "anonymization": "No author/profile fields; explicit handles, emails and Hungarian phone numbers redacted.",
        "limitations": [
            "Checks catalog public GET, original-post parser and revenue policy only.",
            "Does not prove the scheduler, model extraction, database persistence, sending or publishing.",
            "Search candidates are not original-post or current-buyer evidence.",
        ],
        "sources": [],
    }
    environment = {**os.environ, "DATABASE_URL": "sqlite://", "ENVIRONMENT": "test", "PYTHONIOENCODING": "utf-8"}
    for key, url in SOURCES.items():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            report["sources"].append({"source": key, "url": url, "status": "total_time_budget_exhausted"})
            continue
        try:
            completed = subprocess.run(
                [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                 "--app-root", str(args.app_root.resolve()), "--worker", key],
                env=environment, capture_output=True, text=True, encoding="utf-8",
                timeout=min(21.0, remaining), check=False,
            )
            if completed.returncode:
                item = {"source": key, "url": url, "status": "worker_failed", "exit_code": completed.returncode}
            else:
                item = json.loads(completed.stdout)
        except subprocess.TimeoutExpired:
            item = {"source": key, "url": url, "status": "source_time_budget_exhausted"}
        except (ValueError, OSError) as exc:
            item = {"source": key, "url": url, "status": "worker_failed", "error_type": type(exc).__name__}
        report["sources"].append(item)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
