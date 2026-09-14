from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.brand_registry import registry_status
from app.config import Settings


def main() -> None:
    settings = Settings()
    brands = registry_status(settings)
    website_count = sum(len(brand["websites"]) for brand in brands)
    ready_count = sum(
        1
        for brand in brands
        for website in brand["websites"]
        if website["publisher_ready"]
    )
    blog_count = sum(
        1
        for brand in brands
        for website in brand["websites"]
        if website["kind"] == "wordpress_blog"
    )
    print(
        f"Brand registry valid: {len(brands)} brands, "
        f"{website_count} targets, {blog_count} WordPress blogs"
    )
    print(f"Publication-ready websites: {ready_count}/{website_count}")
    for brand in brands:
        for website in brand["websites"]:
            state = "ready" if website["publisher_ready"] else website["status"]
            print(f"- {brand['name']} / {website['key']}: {state}")


if __name__ == "__main__":
    main()
