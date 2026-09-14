from __future__ import annotations

import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/business.manage"]


def main() -> None:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise SystemExit(
            "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET before running."
        )

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8088/"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        port=8088,
        access_type="offline",
        prompt="consent",
        open_browser=True,
    )
    if not credentials.refresh_token:
        raise SystemExit(
            "Google did not return a refresh token. Revoke the old grant and run again."
        )
    print("\nStore this value as GOOGLE_OAUTH_REFRESH_TOKEN:\n")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
