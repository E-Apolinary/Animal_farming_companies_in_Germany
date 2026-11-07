"""Step 11: collect German dairy exporters from the Export-Union directory."""

import re
from urllib.parse import urljoin

from bs4 import NavigableString

from common import (
    ROOT, clean, dedupe, fetch_soup, get_text, now_utc, print_banner,
    save_csv, save_database,
)

CSV_PATH = ROOT / "data/raw/dairy_export_union_companies.csv"
SOURCE_URL = "https://www.export-union.de/de/milchexporte/exportmolkereien"
SOURCE_NAME = "Export-Union Dairy Member Directory"
SECTOR = "Dairy Value Chain - Subsector Unverified"


def extract_record(card):
    company = get_text(card, ".standort-titel")
    if not company:
        return None

    # The address is stored in the card's direct text nodes.
    location_text = clean(" ".join(
        node for node in card.contents if isinstance(node, NavigableString)
    ))
    match = re.search(r"(?<!\d)(\d{5})\s+(.+)$", location_text)
    if not match:
        return None

    postal_code, city = match.group(1), clean(match.group(2))
    street = clean(location_text[:match.start()])

    # The operating-site type is stored as a CSS class.
    type_element = card.select_one(".standortart")
    classes = type_element.get("class", []) if type_element else []
    location_type = " ".join(c for c in classes if c != "standortart")

    profile_link = card.select_one("a.more[href]")

    return {
        "company": company,
        "sector": SECTOR,
        "city": city,
        "postal_code": postal_code,
        "address": ", ".join(p for p in [street, f"{postal_code} {city}"] if p),
        "website": "",
        "email": "",
        "phone": "",
        "description": (
            "Export-Union directory location type: "
            f"{location_type or 'Not specified'}"
        ),
        "source_name": SOURCE_NAME,
        "source_url": (
            urljoin(SOURCE_URL, profile_link["href"]) if profile_link else SOURCE_URL
        ),
        "collected_at": now_utc(),
    }


def collect():
    print("Opening Export-Union directory...")
    cards = fetch_soup(SOURCE_URL).select(".standort-titel-betriebsart-wrapper")
    print("Directory entries found:", len(cards))
    if not cards:
        raise RuntimeError(
            "No company cards found. The directory structure may have changed."
        )
    return dedupe(filter(None, map(extract_record, cards)))


def report(records):
    print()
    print_banner("DAIRY EXPORT DIRECTORY REPORT")
    print("Location records:", len(records))
    print("Unique company names:", len({r["company"].casefold() for r in records}))
    print("Companies with cities:", sum(bool(r["city"]) for r in records))
    print(
        "Company profile links:",
        sum(r["source_url"] != SOURCE_URL for r in records),
    )
    print("=" * 45)


def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 11: DAIRY EXPORT COMPANY DISCOVERY")
    records = collect()
    if not records:
        raise RuntimeError("No German dairy companies extracted.")
    save_csv(records, CSV_PATH)
    save_database(records)
    report(records)
    print("\nDiscovery completed.")


if __name__ == "__main__":
    main()
