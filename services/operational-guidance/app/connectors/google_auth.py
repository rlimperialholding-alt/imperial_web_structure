from __future__ import annotations

from google.auth.credentials import Credentials
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials

from app.config import Settings

GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
SEARCH_CONSOLE_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
BUSINESS_PROFILE_SCOPES = ["https://www.googleapis.com/auth/business.manage"]


def service_account_credentials(settings: Settings, scopes: list[str]) -> Credentials:
    return service_account.Credentials.from_service_account_file(
        settings.google_service_account_file,
        scopes=scopes,
    )


def business_profile_user_credentials(settings: Settings) -> Credentials:
    refresh_token = settings.google_oauth_refresh_token.get_secret_value()
    client_secret = settings.google_oauth_client_secret.get_secret_value()
    if not (settings.google_oauth_client_id and client_secret and refresh_token):
        raise RuntimeError("Google Business Profile OAuth credentials are not configured")
    return UserCredentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_oauth_client_id,
        client_secret=client_secret,
        scopes=BUSINESS_PROFILE_SCOPES,
    )
