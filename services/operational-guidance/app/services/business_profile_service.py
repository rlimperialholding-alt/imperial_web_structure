from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.google_business import GoogleBusinessProfileConnector
from app.models import BusinessProfileLocation, BusinessProfileReview


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sync_business_profile_directory(db: Session, settings: Settings) -> dict[str, int]:
    connector = GoogleBusinessProfileConnector(settings)
    accounts_seen: set[str] = set()
    locations_written = 0
    reviews_written = 0

    for configured in settings.gbp_locations_json:
        brand = configured.get("brand", "unknown")
        account_id = configured.get("account_id", "")
        if not account_id or account_id in accounts_seen:
            continue
        accounts_seen.add(account_id)
        for location in connector.list_locations(account_id):
            location_name = str(location.get("name", ""))
            location_id = location_name.rsplit("/", 1)[-1]
            values = {
                "brand": brand,
                "account_id": account_id,
                "location_id": location_id,
                "title": location.get("title", location_id),
                "store_code": location.get("storeCode"),
                "website_uri": location.get("websiteUri"),
                "phone_numbers": location.get("phoneNumbers", {}),
                "regular_hours": location.get("regularHours", {}),
                "storefront_address": location.get("storefrontAddress", {}),
                "metadata_json": location.get("metadata", {}),
                "raw_payload": location,
                "last_synced_at": datetime.now(UTC),
            }
            statement = insert(BusinessProfileLocation).values(**values)
            statement = statement.on_conflict_do_update(
                constraint="uq_business_profile_location",
                set_={
                    "brand": statement.excluded.brand,
                    "title": statement.excluded.title,
                    "store_code": statement.excluded.store_code,
                    "website_uri": statement.excluded.website_uri,
                    "phone_numbers": statement.excluded.phone_numbers,
                    "regular_hours": statement.excluded.regular_hours,
                    "storefront_address": statement.excluded.storefront_address,
                    "metadata_json": statement.excluded.metadata_json,
                    "raw_payload": statement.excluded.raw_payload,
                    "last_synced_at": statement.excluded.last_synced_at,
                },
            )
            db.execute(statement)
            locations_written += 1

    for configured in settings.gbp_locations_json:
        brand = configured.get("brand", "unknown")
        account_id = configured.get("account_id", "")
        location_id = configured.get("location_id", "")
        if not account_id or not location_id:
            continue
        payload = connector.list_reviews(account_id, location_id)
        for review in payload.get("reviews", []):
            fallback_name = (
                f"accounts/{account_id}/locations/{location_id}/reviews/"
                f"{review.get('reviewId', '')}"
            )
            review_name = str(review.get("name") or fallback_name)
            values: dict[str, Any] = {
                "brand": brand,
                "account_id": account_id,
                "location_id": location_id,
                "review_name": review_name,
                "review_id": review.get("reviewId") or review_name.rsplit("/", 1)[-1],
                "reviewer": review.get("reviewer", {}),
                "star_rating": review.get("starRating"),
                "comment": review.get("comment"),
                "review_reply": review.get("reviewReply", {}),
                "create_time": _parse_datetime(review.get("createTime")),
                "update_time": _parse_datetime(review.get("updateTime")),
                "raw_payload": review,
                "last_synced_at": datetime.now(UTC),
            }
            statement = insert(BusinessProfileReview).values(**values)
            statement = statement.on_conflict_do_update(
                constraint="uq_business_profile_review_name",
                set_={
                    "brand": statement.excluded.brand,
                    "reviewer": statement.excluded.reviewer,
                    "star_rating": statement.excluded.star_rating,
                    "comment": statement.excluded.comment,
                    "review_reply": statement.excluded.review_reply,
                    "create_time": statement.excluded.create_time,
                    "update_time": statement.excluded.update_time,
                    "raw_payload": statement.excluded.raw_payload,
                    "last_synced_at": statement.excluded.last_synced_at,
                },
            )
            db.execute(statement)
            reviews_written += 1

    db.commit()
    return {"locations_written": locations_written, "reviews_written": reviews_written}
