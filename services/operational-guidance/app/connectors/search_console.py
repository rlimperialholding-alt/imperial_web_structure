from __future__ import annotations

from datetime import date
from typing import Any

from googleapiclient.discovery import build

from app.config import Settings
from app.connectors.base import MetricRow, MetricsConnector
from app.connectors.google_auth import SEARCH_CONSOLE_SCOPES, service_account_credentials


class SearchConsoleConnector(MetricsConnector):
    source = "search_console"
    dimensions = ["date", "query", "page", "country", "device"]

    def __init__(self, settings: Settings):
        credentials = service_account_credentials(settings, SEARCH_CONSOLE_SCOPES)
        self.service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)

    def fetch(self, entity_key: str, start_date: date, end_date: date) -> list[MetricRow]:
        rows: list[MetricRow] = []
        start_row = 0
        row_limit = 25_000
        while True:
            body: dict[str, Any] = {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": self.dimensions,
                "type": "web",
                "dataState": "final",
                "rowLimit": row_limit,
                "startRow": start_row,
            }
            response = (
                self.service.searchanalytics().query(siteUrl=entity_key, body=body).execute()
            )
            batch = response.get("rows", [])
            for item in batch:
                keys = item.get("keys", [])
                dimensions = dict(zip(self.dimensions, keys, strict=False))
                rows.append(
                    MetricRow(
                        metric_date=date.fromisoformat(dimensions["date"]),
                        dimensions=dimensions,
                        metrics={
                            "clicks": item.get("clicks", 0),
                            "impressions": item.get("impressions", 0),
                            "ctr": item.get("ctr", 0),
                            "position": item.get("position", 0),
                        },
                        raw_payload=item,
                    )
                )
            if len(batch) < row_limit:
                break
            start_row += row_limit
        return rows
