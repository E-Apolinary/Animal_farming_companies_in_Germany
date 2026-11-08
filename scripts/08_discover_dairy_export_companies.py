"""
STEP 08: Discover dairy exporters.

Source: Export-Union für Milchprodukte, list of export dairies.

Each card holds the company name, a CSS class naming the type of site
(e.g. production plant), and the address as loose text. Contact details
live on each company's profile page and are filled in by step 18.
"""

import re
from urllib.parse import urljoin

from bs4 import NavigableString

from common import (
    RAW_DIR, clean, dedupe, fetch_soup, get_text, make_record,
    print_banner, print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "dairy_export_companies.csv"
SOURCE_URL = "https://www.export-union.de/de/milchexporte/exportmolkereien"
SOURCE_NAME = "Export-Union Dairy Member Directory"
SECTOR = "Dairy Value Chain - Subsector Unverified"

# "Street 1 12345 City": the postcode starts the city part.
LOCATION_RE = re.compile(r"(?<!\d)(\d{5})\s+(.+)$")


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def extract_record(card):
    """Turn one directory card into a record, or None if not German."""
    company = get_text(card, ".standort-titel")

    if not company:
        return None

    # The address is the card's own text, outside any child element.
    location = clean(" ".join(n for n in card.contents if isinstance(n, NavigableString)))
    match = LOCATION_RE.search(location)

    if not match:
        return None

    postal_code, city = match.group(1), clean(match.group(2))
    street = clean(location[:match.start()])

    # The site type is stored as an extra CSS class on .standortart.
    type_element = card.select_one(".standortart")
    classes = type_element.get("class", []) if type_element else []
    site_type = " ".join(c for c in classes if c != "standortart") or "Not specified"

    profile = card.select_one("a.more[href]")

    return make_record(
        company=company,
        sector=SECTOR,
        city=city,
        postal_code=postal_code,
        address=", ".join(p for p in (street, f"{postal_code} {city}") if p),
        description=f"Export-Union directory location type: {site_type}",
        source_name=SOURCE_NAME,
        # The profile page is where step 18 finds the contact details.
        source_url=urljoin(SOURCE_URL, profile["href"]) if profile else SOURCE_URL,
    )


def collect():
    print("Opening Export-Union directory...")
    cards = fetch_soup(SOURCE_URL, timeout=60).select(".standort-titel-betriebsart-wrapper")
    print("Directory entries found:", len(cards))

    if not cards:
        raise RuntimeError("No company cards found. The directory structure may have changed.")

    return dedupe(filter(None, map(extract_record, cards)))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 08: DAIRY EXPORT COMPANY DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No German dairy companies extracted.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("DAIRY EXPORT DISCOVERY REPORT", records)
    print("With profile link:", sum(r["source_url"] != SOURCE_URL for r in records))


if __name__ == "__main__":
    main()
