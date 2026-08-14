from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _alembic(
    database_url: str, command: str, revision: str, workspace: Path
) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=workspace,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    workspace = Path(__file__).parents[1]
    with tempfile.TemporaryDirectory(prefix="imperial-mkt-migration-") as temp_dir:
        database_path = Path(temp_dir) / "migration.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        _alembic(database_url, "upgrade", "head", workspace)
        _alembic(database_url, "downgrade", "20260802_0040", workspace)
        engine = create_engine(database_url)
        pre_migration_columns = {
            column["name"] for column in inspect(engine).get_columns("mkt_leads")
        }
        if "consent_management_token" in pre_migration_columns:
            raise RuntimeError("Revision 0040 unexpectedly contains the consent token.")
        now = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO mkt_leads ("
                    "lead_id, dedupe_key, source, channel, full_name, lead_type, "
                    "estimated_budget_huf, privacy_notice_accepted, privacy_notice_version, "
                    "marketing_consent, score, score_reasons_json, status, signal_count, "
                    "captured_at, last_captured_at, created_at, updated_at"
                    ") VALUES ("
                    ":lead_id, :dedupe_key, :source, :channel, :full_name, :lead_type, "
                    ":budget, :privacy, :version, :consent, :score, :reasons, :status, "
                    ":signals, :captured, :last_captured, :created, :updated"
                    ")"
                ),
                {
                    "lead_id": "LEAD-PREMIGRATION",
                    "dedupe_key": "a" * 64,
                    "source": "legacy",
                    "channel": "email",
                    "full_name": "Migrációs Lead",
                    "lead_type": "b2c",
                    "budget": 0,
                    "privacy": True,
                    "version": "legacy-v1",
                    "consent": True,
                    "score": 50,
                    "reasons": "[]",
                    "status": "scored",
                    "signals": 1,
                    "captured": now,
                    "last_captured": now,
                    "created": now,
                    "updated": now,
                },
            )

        _alembic(database_url, "upgrade", "head", workspace)
        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("mkt_leads")
        }
        if columns["consent_management_token"]["nullable"] is not False:
            raise RuntimeError("The consent token remained nullable after migration.")
        indexes = {
            index["name"]: index for index in inspect(engine).get_indexes("mkt_leads")
        }
        if indexes["ix_mkt_leads_consent_management_token"]["unique"] != 1:
            raise RuntimeError("The consent token index is not unique.")
        with engine.connect() as connection:
            token = connection.execute(
                text(
                    "SELECT consent_management_token FROM mkt_leads "
                    "WHERE lead_id = 'LEAD-PREMIGRATION'"
                )
            ).scalar_one()
        if not token or len(token) != 64:
            raise RuntimeError("The existing lead did not receive a valid backfilled token.")
    print("marketing-consent-nonempty-migration-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
