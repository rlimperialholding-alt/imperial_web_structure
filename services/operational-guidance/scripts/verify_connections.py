from __future__ import annotations

from datetime import date, timedelta

from app.config import get_settings
from app.connectors.ga4 import GA4Connector
from app.connectors.google_business import GoogleBusinessProfileConnector
from app.connectors.ingatlan import IngatlanConnector
from app.connectors.search_console import SearchConsoleConnector


def main() -> None:
    settings = get_settings()
    yesterday = date.today() - timedelta(days=1)

    if settings.ga4_properties_json:
        connector = GA4Connector(settings)
        for target in settings.ga4_properties_json:
            rows = connector.fetch(target["property_id"], yesterday, yesterday)
            print(f"GA4 {target['brand']}: {len(rows)} rows")
    else:
        print("GA4: skipped, no configured property")

    if settings.search_console_sites_json:
        connector = SearchConsoleConnector(settings)
        for target in settings.search_console_sites_json:
            rows = connector.fetch(target["site_url"], yesterday, yesterday)
            print(f"Search Console {target['brand']}: {len(rows)} rows")
    else:
        print("Search Console: skipped, no configured site")

    if settings.google_oauth_refresh_token.get_secret_value():
        accounts = GoogleBusinessProfileConnector(settings).list_accounts()
        print(f"Google Business Profile: {len(accounts)} accessible accounts")
    else:
        print("Google Business Profile: skipped, OAuth is not configured")

    if settings.ingatlan_username:
        with IngatlanConnector(settings) as connector:
            ids = connector.list_ad_ids()
        print(f"ingatlan.com: {len(ids)} advertisement IDs")
    else:
        print("ingatlan.com: skipped, credentials are not configured")


if __name__ == "__main__":
    main()
