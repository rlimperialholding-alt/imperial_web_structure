from __future__ import annotations

from datetime import date
from typing import Any

import httpx
from google.auth.transport.requests import Request

from app.config import Settings
from app.connectors.base import MetricRow, MetricsConnector
from app.connectors.google_auth import business_profile_user_credentials


class GoogleBusinessProfileConnector(MetricsConnector):
    source = "google_business_profile"
    performance_base_url = "https://businessprofileperformance.googleapis.com/v1"
    my_business_base_url = "https://mybusiness.googleapis.com/v4"
    account_management_base_url = "https://mybusinessaccountmanagement.googleapis.com/v1"
    business_information_base_url = "https://mybusinessbusinessinformation.googleapis.com/v1"
    metrics = [
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
        "WEBSITE_CLICKS",
        "CALL_CLICKS",
        "BUSINESS_DIRECTION_REQUESTS",
    ]

    def __init__(self, settings: Settings):
        self.credentials = business_profile_user_credentials(settings)

    def _headers(self) -> dict[str, str]:
        if not self.credentials.valid:
            self.credentials.refresh(Request())
        return {
            "Authorization": f"Bearer {self.credentials.token}",
            "Accept": "application/json",
        }

    @staticmethod
    def _resource_id(value: str, prefix: str) -> str:
        marker = f"{prefix}/"
        return value.split(marker, 1)[1].split("/", 1)[0] if marker in value else value

    @classmethod
    def _account_name(cls, account_id: str) -> str:
        return f"accounts/{cls._resource_id(account_id, 'accounts')}"

    @classmethod
    def _location_name(cls, location_id: str) -> str:
        return f"locations/{cls._resource_id(location_id, 'locations')}"

    @staticmethod
    def _date_params(prefix: str, value: date) -> dict[str, int]:
        return {
            f"{prefix}.year": value.year,
            f"{prefix}.month": value.month,
            f"{prefix}.day": value.day,
        }

    def fetch(self, entity_key: str, start_date: date, end_date: date) -> list[MetricRow]:
        location = self._location_name(entity_key)
        params: list[tuple[str, str | int]] = [("dailyMetrics", metric) for metric in self.metrics]
        params += list(self._date_params("dailyRange.start_date", start_date).items())
        params += list(self._date_params("dailyRange.end_date", end_date).items())
        url = f"{self.performance_base_url}/{location}:fetchMultiDailyMetricsTimeSeries"
        with httpx.Client(timeout=45) as client:
            response = client.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            payload = response.json()

        by_date: dict[date, dict[str, Any]] = {}
        series_groups = payload.get("multiDailyMetricTimeSeries", [])
        for group in series_groups:
            for series in group.get("dailyMetricTimeSeries", []):
                metric_name = series.get("dailyMetric", "UNKNOWN")
                sub_entity = series.get("dailySubEntityType")
                for point in series.get("timeSeries", {}).get("datedValues", []):
                    date_value = point["date"]
                    point_date = date(
                        int(date_value["year"]),
                        int(date_value["month"]),
                        int(date_value["day"]),
                    )
                    key = metric_name if not sub_entity else f"{metric_name}:{sub_entity}"
                    by_date.setdefault(point_date, {})[key] = int(point.get("value", 0))

        return [
            MetricRow(
                metric_date=metric_date,
                dimensions={"location": location},
                metrics=metrics,
                raw_payload={"location": location, "metrics": metrics},
            )
            for metric_date, metrics in sorted(by_date.items())
        ]

    def list_accounts(self) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        page_token: str | None = None
        with httpx.Client(timeout=45) as client:
            while True:
                params: dict[str, Any] = {"pageSize": 20}
                if page_token:
                    params["pageToken"] = page_token
                response = client.get(
                    f"{self.account_management_base_url}/accounts",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                payload = response.json()
                accounts.extend(payload.get("accounts", []))
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
        return accounts

    def list_locations(self, account_id: str) -> list[dict[str, Any]]:
        parent = self._account_name(account_id)
        read_mask = ",".join(
            [
                "name",
                "title",
                "storeCode",
                "websiteUri",
                "phoneNumbers",
                "regularHours",
                "storefrontAddress",
                "metadata",
                "profile",
                "categories",
                "openInfo",
            ]
        )
        locations: list[dict[str, Any]] = []
        page_token: str | None = None
        with httpx.Client(timeout=45) as client:
            while True:
                params: dict[str, Any] = {"pageSize": 100, "readMask": read_mask}
                if page_token:
                    params["pageToken"] = page_token
                response = client.get(
                    f"{self.business_information_base_url}/{parent}/locations",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                payload = response.json()
                locations.extend(payload.get("locations", []))
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
        return locations

    def list_reviews(self, account_id: str, location_id: str) -> dict[str, Any]:
        account = self._resource_id(account_id, "accounts")
        location = self._resource_id(location_id, "locations")
        parent = f"accounts/{account}/locations/{location}"
        all_reviews: list[dict[str, Any]] = []
        page_token: str | None = None
        average_rating: float | None = None
        total_review_count: int | None = None
        with httpx.Client(timeout=45) as client:
            while True:
                params: dict[str, Any] = {"pageSize": 50, "orderBy": "updateTime desc"}
                if page_token:
                    params["pageToken"] = page_token
                response = client.get(
                    f"{self.my_business_base_url}/{parent}/reviews",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                payload = response.json()
                all_reviews.extend(payload.get("reviews", []))
                average_rating = payload.get("averageRating", average_rating)
                total_review_count = payload.get("totalReviewCount", total_review_count)
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
        return {
            "reviews": all_reviews,
            "averageRating": average_rating,
            "totalReviewCount": total_review_count,
        }

    def reply_to_review(
        self, account_id: str, location_id: str, review_id: str, comment: str
    ) -> dict[str, Any]:
        account = self._resource_id(account_id, "accounts")
        location = self._resource_id(location_id, "locations")
        review = self._resource_id(review_id, "reviews")
        name = f"accounts/{account}/locations/{location}/reviews/{review}"
        with httpx.Client(timeout=45) as client:
            response = client.put(
                f"{self.my_business_base_url}/{name}/reply",
                json={"comment": comment},
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    def create_local_post(
        self, account_id: str, location_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        account = self._resource_id(account_id, "accounts")
        location = self._resource_id(location_id, "locations")
        parent = f"accounts/{account}/locations/{location}"
        with httpx.Client(timeout=45) as client:
            response = client.post(
                f"{self.my_business_base_url}/{parent}/localPosts",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()
