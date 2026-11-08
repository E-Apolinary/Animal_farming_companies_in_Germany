"""
STEP 06: Discover poultry value chain companies.

Source: NGW (Niedersächsische Geflügelwirtschaft) member directory.

Each member is a .t_entry card with separate elements for name, street,
postcode, city, phone and a free-text description.
"""

from urllib.parse import urljoin

from common import (
    RAW_DIR, check_count, dedupe, fetch_soup, get_text, make_record,
    print_banner, print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "poultry_companies.csv"
SOURCE_URL = "https://www.ngw-landesverband.de/mitglieder"
SOURCE_NAME = "NGW Poultry Member Directory"
SECTOR = "Poultry Value Chain - Subsector Unverified"

EXPECTED_COUNT = (5, 100)


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def extract_record(card):
    """Turn one member card into a record, or None if it has no name."""

    def field(name):
        # Text kept as published: company and address form the upsert key.
        return get_text(card, f".t_entry_{name}", squash=False)

    company = field("name_1")

    if not company:
        return None

    website = card.select_one(".t_entry_www a[href]")
    street, postal_code, city = field("street"), field("postal_code"), field("city")

    return make_record(
        company=company,
        sector=SECTOR,
        city=city,
        postal_code=postal_code,
        address=" | ".join(p for p in (street, f"{postal_code} {city}".strip()) if p),
        website=urljoin(SOURCE_URL, website["href"].strip()) if website else "",
        # Email addresses on this site are obfuscated; they are left blank
        # rather than stored wrongly.
        phone=field("phone"),
        description=field("observations"),
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
    )


def collect():
    print("Opening NGW member directory...")
    cards = fetch_soup(SOURCE_URL, timeout=30).select(".t_entry")
    print("Profile cards found:", len(cards))

    return dedupe(filter(None, map(extract_record, cards)))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 06: POULTRY COMPANY DISCOVERY")

    records = collect()
    check_count(records, *EXPECTED_COUNT, SOURCE_NAME)

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("POULTRY DISCOVERY REPORT", records)
    print("With description:", sum(bool(r["description"]) for r in records))


if __name__ == "__main__":
    main()
