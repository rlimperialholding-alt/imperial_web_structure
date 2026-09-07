"""One real brand generation/review in a disposable, delivery-free database.

Example in a separate application container (mount only the DeepSeek secret):
    python /trial/verify_content_factory_live_model.py --platform-root /app \
        --output /trial-output/content-factory-model.json

The CLI always uses the real complete_json client. Only offline unit tests may
inject a callable into run_trial; such results are labelled offline_test_double.
Do not run this inside an application worker: run_trial requires fresh imports
and replaces the process environment before importing any application module.
The private SQLite usage ledger does not include production monthly spending.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

SOURCE_VERSION = "2026-09-07.v1"
TRIAL_BRANDS = (
    "Property360", "RED Property", "Venture Studio", "Bautica", "BauFreund",
    "Prefab", "TimberHaus", "Danish Fabrik", "Imperial", "Casa Moderna", "Everyday Homes",
)


def _allowed_model_purposes(brand_id: str) -> set[str]:
    if brand_id not in TRIAL_BRANDS:
        raise TrialIsolationError("unsupported_trial_brand")
    return {f"{purpose}:{brand_id}" for purpose in (
        "canonical_daily_content_factory", "canonical_daily_content_deterministic_repair",
        "canonical_daily_content_release_review", "canonical_daily_content_review_repair",
    )}
DEEPSEEK_ENV = {
    "DEEPSEEK_API_KEY_FILE",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_ROUTINE_MODEL",
    "DEEPSEEK_HIGH_STAKES_MODEL",
    "DEEPSEEK_MONTHLY_BUDGET_USD",
    "DEEPSEEK_INPUT_USD_PER_MILLION",
    "DEEPSEEK_OUTPUT_USD_PER_MILLION",
}
SYSTEM_ENV = {
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "TZ",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
}


class TrialIsolationError(RuntimeError):
    """An attempted side effect or a trial limit ends this process-local run."""


def _provider_response_diagnostics(data: object) -> dict:
    """Capture bounded final text only; never headers/auth or reasoning text."""
    value = data if isinstance(data, dict) else {}
    choices = value.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    choice = choice if isinstance(choice, dict) else {}
    message = choice.get("message")
    message = message if isinstance(message, dict) else {}
    content = message.get("content")
    final_text = content if isinstance(content, str) else ""
    raw_usage = value.get("usage")
    raw_usage = raw_usage if isinstance(raw_usage, dict) else {}
    usage = {
        key: raw_usage[key]
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        )
        if isinstance(raw_usage.get(key), (int, float))
    }
    return {
        "provider_response_id": value.get("id"),
        "provider_model_id": value.get("model"),
        "finish_reason": choice.get("finish_reason"),
        "message_content": final_text[:16000],
        "message_content_type": type(content).__name__,
        "message_content_chars": len(final_text),
        "message_content_sha256": hashlib.sha256(
            final_text.encode("utf-8")
        ).hexdigest(),
        "message_content_truncated": len(final_text) > 16000,
        "usage": usage,
    }


def _isolated_environment(directory: Path) -> None:
    # Retain no production database, publishing, email, session or signing key.
    retained = {
        key: value
        for key, value in os.environ.items()
        if key in DEEPSEEK_ENV | SYSTEM_ENV
    }
    os.environ.clear()
    os.environ.update(retained)
    os.environ.update(
        {
            "DATABASE_URL": "sqlite:///" + (directory / "trial.sqlite3").as_posix(),
            "ENVIRONMENT": "test",
            "PLATFORM_RUNTIME_ROOT": str(directory / "runtime"),
            "SESSION_SECRET": secrets.token_hex(32),
            "CANONICAL_CONTENT_FACTORY_ENABLED": "true",
            "CANONICAL_REVENUE_POLICY_ENABLED": "true",
        }
    )


def run_trial(
    platform_root: Path,
    *,
    model_client=None,
    brand_id: str = "Property360",
    now: datetime | None = None,
    max_calls: int = 6,
    max_seconds: int = 240,
    max_cost_usd: float = 0.20,
    radar_fixture: Path | None = None,
) -> dict:
    """Run once. model_client is an offline-test seam, absent from the CLI."""
    if any(name == "app" or name.startswith("app.") for name in sys.modules):
        raise TrialIsolationError("fresh_process_required")
    if not (
        1 <= max_calls <= 6 and 1 <= max_seconds <= 240 and 0 < max_cost_usd <= 0.20
    ):
        raise TrialIsolationError("invalid_trial_limits")
    allowed_purposes = _allowed_model_purposes(brand_id)
    if radar_fixture is not None and brand_id != "BauFreund":
        raise TrialIsolationError("radar_replay_requires_baufreund_brand")
    started = time.monotonic()
    report = {
        "schema": "content-factory-live-model-trial-v1",
        "mode": "offline_test_double" if model_client else "live_provider",
        "status": "failed",
        "brand_id": brand_id,
        "source_mode": "anonymized_original_source_replay" if radar_fixture else "approved_brand_documents",
        "source_manifest_version": SOURCE_VERSION,
        "started_at": datetime.now(UTC).isoformat(),
        "database": "disposable_sqlite",
        "production_database_used": False,
        "signature_scope": "ephemeral_trial_only_no_publication_authority",
        "monthly_ledger_scope": "isolated_trial_excludes_production_spending",
        "limits": {
            "max_calls": max_calls,
            "max_seconds": max_seconds,
            "max_estimated_cost_usd": max_cost_usd,
        },
        "model_calls": [],
        "provider_responses": [],
        "sources": [],
        "external_sends": 0,
        "publications": 0,
        "enqueue_calls": 0,
        "forbidden_action_attempts": [],
        "checks": {},
    }
    with tempfile.TemporaryDirectory(prefix="content_factory_model_trial_") as temp:
        directory = Path(temp)
        _isolated_environment(directory)
        sys.path.insert(0, str(platform_root.resolve()))
        from app.autonomous_publishing import service as publishing_service
        from app.autonomous_publishing.models import PublishingJobRecord
        from app.database import Base, SessionLocal, engine
        from app.growth_ops import deepseek, processing
        from app.growth_ops.models import (
            CanonicalEmailDelivery,
            CanonicalInternalHandoff,
            CanonicalLLMUsage,
            DailyContentObligation,
        )
        from app.seed import seed_content_factory_source_inventory
        from sqlalchemy import func, select

        if engine.url.get_backend_name() != "sqlite" or (
            Path(str(engine.url.database)).resolve() != directory / "trial.sqlite3"
        ):
            raise TrialIsolationError("isolated_database_binding_failed")
        cfg = deepseek.settings()
        report["runtime_code_sha256"] = {
            name: hashlib.sha256(
                (platform_root / "app" / "growth_ops" / name).read_bytes()
            ).hexdigest()
            for name in ("processing.py", "deepseek.py", "revenue_policy.py")
        }
        provider_url = cfg.deepseek_base_url.rstrip("/") + "/chat/completions"
        parsed = urlsplit(provider_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.deepseek.com"
            or parsed.path != "/chat/completions"
            or parsed.query
            or parsed.fragment
        ):
            raise TrialIsolationError("unexpected_deepseek_endpoint")
        report["configured_models"] = {
            "generator": cfg.deepseek_routine_model,
            "reviewer": cfg.deepseek_high_stakes_model,
        }
        ephemeral_key = secrets.token_bytes(32)
        active_call = False
        reserved_cost = 0.0
        actual_client = model_client or deepseek.complete_json

        def forbidden(name):
            def stop(*_args, **_kwargs):
                report["forbidden_action_attempts"].append(name)
                if name in {"submit_job", "enqueue_daily_publications"}:
                    report["enqueue_calls"] += 1
                raise TrialIsolationError("forbidden_trial_action:" + name)

            return stop

        def bounded_client(db, **kwargs):
            nonlocal active_call, reserved_cost
            purpose = kwargs.get("purpose")
            if purpose not in allowed_purposes:
                raise TrialIsolationError("unexpected_model_purpose")
            if len(report["model_calls"]) >= max_calls:
                raise TrialIsolationError("model_call_limit")
            if time.monotonic() - started >= max_seconds:
                raise TrialIsolationError("trial_time_limit")
            if not model_client:
                # UTF-8 bytes + framing is conservative for the text tokenizer;
                # charge every attempted request against this additional cap.
                prompt_bytes = sum(
                    len(str(kwargs[key]).encode("utf-8"))
                    for key in ("system_prompt", "user_prompt")
                )
                upper_cost = (
                    (prompt_bytes + 4096) * cfg.deepseek_input_usd_per_million
                    + int(kwargs["max_tokens"]) * cfg.deepseek_output_usd_per_million
                ) / 1_000_000
                if reserved_cost + upper_cost > max_cost_usd:
                    raise TrialIsolationError("trial_cost_limit")
                reserved_cost += upper_cost
            record = {"purpose": purpose, "status": "started"}
            report["model_calls"].append(record)
            active_call = True
            try:
                result = actual_client(db, **kwargs)
                record.update(
                    {
                        "status": "completed",
                        "client_request_id": result.request_id,
                        "model_id": result.model,
                        "actual_output": json.loads(result.content),
                        "response_sha256": hashlib.sha256(
                            result.content.encode()
                        ).hexdigest(),
                        "prompt_tokens": getattr(result, "prompt_tokens", None),
                        "completion_tokens": getattr(result, "completion_tokens", None),
                        "estimated_cost_usd": getattr(
                            result, "estimated_cost_usd", None
                        ),
                    }
                )
                return result
            except Exception as exc:
                record.update(status="failed", error_type=type(exc).__name__)
                raise
            finally:
                active_call = False

        import httpx

        real_http_send = httpx.Client.send

        def restricted_http_send(client, request, **kwargs):
            if (
                model_client is not None
                or not active_call
                or request.method != "POST"
                or str(request.url) != provider_url
            ):
                return forbidden("unexpected_http_request")()
            response = real_http_send(client, request, **kwargs)
            # complete_json request_id is locally assigned. Preserve the provider's
            # separate response ID/model as additional evidence, never headers.
            data = response.json() if response.is_success else {}
            report["provider_responses"].append(
                {
                    "status_code": response.status_code,
                    "purpose": report["model_calls"][-1]["purpose"],
                    **_provider_response_diagnostics(data),
                }
            )
            return response

        def deadline(_signum, _frame):
            raise TrialIsolationError("trial_time_limit")

        try:
            with ExitStack() as guards:
                if hasattr(signal, "setitimer"):
                    prior_handler = signal.signal(signal.SIGALRM, deadline)
                    signal.setitimer(
                        signal.ITIMER_REAL,
                        max(0.01, max_seconds - (time.monotonic() - started)),
                    )
                    guards.callback(signal.signal, signal.SIGALRM, prior_handler)
                    guards.callback(signal.setitimer, signal.ITIMER_REAL, 0)
                guards.enter_context(
                    patch.object(processing, "ACTIVE_CONTENT_BRANDS", (brand_id,))
                )
                guards.enter_context(
                    patch.object(
                        processing, "_quality_release_secret", lambda: ephemeral_key
                    )
                )
                guards.enter_context(
                    patch.object(processing, "complete_json", bounded_client)
                )
                for name in (
                    "submit_job",
                    "enqueue_daily_publications",
                    "send_publication_digest",
                    "send_internal_handoff",
                    "sync_canonical_image",
                    "SMTPEmailAdapter",
                ):
                    guards.enter_context(
                        patch.object(processing, name, forbidden(name))
                    )
                guards.enter_context(
                    patch.object(
                        publishing_service, "submit_job", forbidden("submit_job")
                    )
                )
                guards.enter_context(patch("smtplib.SMTP", forbidden("smtp")))
                guards.enter_context(patch("smtplib.SMTP_SSL", forbidden("smtp_ssl")))
                guards.enter_context(
                    patch.object(httpx.Client, "send", restricted_http_send)
                )
                guards.enter_context(
                    patch.object(httpx.AsyncClient, "send", forbidden("async_http"))
                )
                Base.metadata.create_all(bind=engine)
                with SessionLocal() as db:
                    seed_content_factory_source_inventory(db)
                    db.commit()
                    current = now or datetime.now(UTC)
                    if radar_fixture is not None:
                        from app.growth_ops import catalog
                        from app.growth_ops.models import QuestionRadarTopic

                        fixture_bytes = radar_fixture.read_bytes()
                        _, candidates = catalog._page_evidence(
                            fixture_bytes.decode("utf-8"),
                            base_url="https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25",
                            limit=24000,
                        )
                        candidate = next(item for item in candidates if "/1w8rs4c/" in item["url"])
                        question = candidate["label"].partition("[SOURCE_PAGE_EVIDENCE]")[0].strip()
                        metadata = processing._source_page_metadata_from_label(candidate["label"])
                        freshness = processing._question_freshness(
                            {**metadata, "source_url": candidate["url"], "question": question},
                            evidence_text=candidate["label"], observed_at=current,
                            require_source_date_proof=True,
                        )
                        if freshness.get("published_at_raw") != "2026-09-06T09:45:34+00:00":
                            raise TrialIsolationError("unexpected_radar_fixture_source_date")
                        identity = processing._radar_identity_hash(candidate["url"])
                        topic = QuestionRadarTopic(
                            topic_id="QRT-TRIAL-ORIGINAL-MUNKADIJAK", brand_id=brand_id,
                            local_date=current.date(), question=question, source_url=candidate["url"],
                            use_case="felújítási munkadíj", classification="observed_literal",
                            identity_hash=identity, dedupe_hash=identity,
                            **{key: freshness[key] for key in (
                                "published_at", "published_at_raw", "age_days", "active_status",
                                "existing_answer_count", "freshness_decision", "eligibility_status",
                            )},
                            rejection_reasons_json=json.dumps(freshness["reasons"]),
                        )
                        db.add(topic)
                        db.commit()
                        report["radar_replay"] = {
                            "topic_id": topic.topic_id, "source_url": topic.source_url,
                            "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
                            "original_problem": question,
                            "published_at_raw": freshness["published_at_raw"],
                            "source_revalidation_mode": "same_anonymized_original_fixture",
                            "source_revalidation_calls": 0,
                        }

                        def replay_source(requested_topic, *, now):
                            if requested_topic.topic_id != topic.topic_id:
                                raise TrialIsolationError("unexpected_radar_replay_topic")
                            report["radar_replay"]["source_revalidation_calls"] += 1
                            return {
                                "source_url": topic.source_url, "source_text": question,
                                "published_at": freshness["published_at"],
                                "published_at_raw": freshness["published_at_raw"],
                                "active_status": "active",
                            }

                        guards.enter_context(patch.object(processing, "_refresh_topic_source", replay_source))
                    sources = processing._approved_brand_facts(
                        db, brand_id, current=current
                    )
                    if not sources or any(
                        item["version"] != SOURCE_VERSION for item in sources
                    ):
                        raise TrialIsolationError(
                            "expected_approved_source_version_missing"
                        )
                    report["sources"] = sources
                    manifest = (
                        platform_root / "app" / "content_factory_source_manifest.json"
                    )
                    report["source_manifest_sha256"] = hashlib.sha256(
                        manifest.read_bytes()
                    ).hexdigest()
                    try:
                        report["pipeline_result"] = processing.generate_daily_content(
                            db, now=current
                        )
                    except Exception as exc:  # noqa: BLE001 - redact all failure details
                        # No exception messages/tracebacks: they might include a
                        # provider response, authentication material or URL.
                        report["error_type"] = type(exc).__name__
                    rows = list(db.scalars(select(DailyContentObligation)))
                    report["obligations"] = []
                    for row in rows:
                        evidence = json.loads(row.evidence_json or "{}")
                        package = (
                            evidence
                            if isinstance(evidence, dict)
                            else {"pipeline_evidence": evidence}
                        )
                        signature = package.get("quality_gate_manifest", {}).pop(
                            "hmac_sha256", None
                        )
                        report["obligations"].append(
                            {
                                "brand_id": row.brand_id,
                                "status": row.status,
                                "trial_signature_present": bool(signature),
                                "output": package,
                            }
                        )
                    counts = {
                        "publishing_jobs": db.scalar(
                            select(func.count()).select_from(PublishingJobRecord)
                        ),
                        "email_deliveries": db.scalar(
                            select(func.count()).select_from(CanonicalEmailDelivery)
                        ),
                        "internal_handoffs": db.scalar(
                            select(func.count()).select_from(CanonicalInternalHandoff)
                        ),
                    }
                    report["delivery_database_rows"] = counts
                    usage = list(db.scalars(select(CanonicalLLMUsage)))
                    report["usage_rows"] = len(usage)
                    report["checks"] = {
                        "one_target_brand_obligation": len(rows) == 1
                        and rows[0].brand_id == brand_id,
                        "existing_quality_review_passed": len(rows) == 1
                        and rows[0].status == "release_passed",
                        "generator_and_reviewer_completed": all(
                            any(
                                call["purpose"] == purpose
                                and call["status"] == "completed"
                                for call in report["model_calls"]
                            )
                            for purpose in allowed_purposes
                            if "repair" not in purpose
                        ),
                        "no_delivery_actions": not any(counts.values())
                        and not report["forbidden_action_attempts"],
                        "provider_evidence_present": bool(model_client)
                        or (
                            len(usage) >= 2
                            and len(report["provider_responses"]) >= 2
                            and all(
                                item["provider_response_id"]
                                and item["provider_model_id"]
                                for item in report["provider_responses"]
                                if item["status_code"] == 200
                            )
                        ),
                    }
                    if radar_fixture is not None:
                        chosen = report["obligations"][0]["output"].get("revenue_intent", {})
                        report["checks"]["original_radar_source_used"] = (
                            chosen.get("radar_topic_id") == "QRT-TRIAL-ORIGINAL-MUNKADIJAK"
                            and report["radar_replay"]["source_revalidation_calls"] >= 1
                        )
                    if all(report["checks"].values()):
                        report["status"] = "passed"
        except Exception as exc:  # noqa: BLE001 - redact all failure details
            report["error_type"] = type(exc).__name__
        finally:
            engine.dispose()
        report["reserved_estimated_cost_usd"] = round(reserved_cost, 6)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["temporary_database_removed"] = not directory.exists()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "services" / "platform-core",
    )
    parser.add_argument("--brand", choices=TRIAL_BRANDS, default="Property360")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--radar-fixture", type=Path)
    args = parser.parse_args()
    # Resolve before environment/runtime isolation; never overwrite an old trial.
    output_path = args.output.resolve()
    if output_path.exists():
        parser.error("output already exists; use a new filename")
    try:
        report = run_trial(
            args.platform_root.resolve(), brand_id=args.brand,
            radar_fixture=args.radar_fixture.resolve() if args.radar_fixture else None,
        )
    except Exception as exc:  # noqa: BLE001 - redact all failure details
        report = {
            "status": "failed",
            "mode": "live_provider",
            "error_type": type(exc).__name__,
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report["mode"],
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
