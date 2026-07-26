from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest

from app.config import Settings
from app.connectors.base import MetricRow, MetricsConnector
from app.connectors.google_auth import GA4_SCOPES, service_account_credentials


class GA4Connector(MetricsConnector):
    source = "ga4"
    reports: ClassVar[list[dict[str, list[str] | str]]] = [
        {
            "name": "page_behavior",
            "dimensions": ["date", "pagePathPlusQueryString"],
            "metrics": [
                "screenPageViews",
                "activeUsers",
                "keyEvents",
                "userEngagementDuration",
            ],
        },
        {
            "name": "acquisition_channel",
            "dimensions": ["date", "sessionDefaultChannelGroup"],
            "metrics": [
                "sessions",
                "totalUsers",
                "engagedSessions",
                "keyEvents",
                "engagementRate",
            ],
        },
        {
            "name": "landing_page",
            "dimensions": ["date", "landingPagePlusQueryString"],
            "metrics": ["sessions", "engagedSessions", "keyEvents", "engagementRate"],
        },
    ]

    def __init__(self, settings: Settings):
        credentials = service_account_credentials(settings, GA4_SCOPES)
        self.client = BetaAnalyticsDataClient(credentials=credentials)

    @staticmethod
    def _number(value: str) -> int | float:
        parsed = Decimal(value or "0")
        return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)

    def _fetch_report(
        self,
        property_name: str,
        report_name: str,
        dimension_names: list[str],
        metric_names: list[str],
        start_date: date,
        end_date: date,
    ) -> list[MetricRow]:
        rows: list[MetricRow] = []
        offset = 0
        page_size = 100_000

        while True:
            request = RunReportRequest(
                property=property_name,
                dimensions=[Dimension(name=name) for name in dimension_names],
                metrics=[Metric(name=name) for name in metric_names],
                date_ranges=[
                    DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())
                ],
                limit=page_size,
                offset=offset,
                return_property_quota=True,
            )
            response = self.client.run_report(request)
            for row in response.rows:
                dimensions = {
                    name: value.value
                    for name, value in zip(
                        dimension_names,
                        row.dimension_values,
                        strict=True,
                    )
                }
                dimensions["report_type"] = report_name
                metrics = {
                    name: self._number(value.value)
                    for name, value in zip(metric_names, row.metric_values, strict=True)
                }
                metric_date = datetime.strptime(dimensions["date"], "%Y%m%d").date()
                rows.append(
                    MetricRow(
                        metric_date=metric_date,
                        dimensions=dimensions,
                        metrics=metrics,
                        raw_payload={
                            "report_type": report_name,
                            "dimensions": dimensions,
                            "metrics": metrics,
                        },
                    )
                )

            offset += len(response.rows)
            if not response.rows or offset >= response.row_count:
                break

        return rows

    def fetch(self, entity_key: str, start_date: date, end_date: date) -> list[MetricRow]:
        property_name = (
            entity_key if entity_key.startswith("properties/") else f"properties/{entity_key}"
        )
        rows: list[MetricRow] = []
        for report in self.reports:
            rows.extend(
                self._fetch_report(
                    property_name=property_name,
                    report_name=str(report["name"]),
                    dimension_names=list(report["dimensions"]),
                    metric_names=list(report["metrics"]),
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        return rows
