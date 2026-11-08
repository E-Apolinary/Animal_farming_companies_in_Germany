"""
STEP 07: Discover dairy processing companies.

Source: MIV (Milchindustrie-Verband) member directory.

Each member card states its type: a dairy ("Firmensitz"), a supporting
supplier ("Firmensitz Förderer") or the association office itself,
which is skipped.
"""

from common import (
    POSTCODE_CITY_RE, RAW_DIR, dedupe, fetch_soup, get_text, make_record,
    new_session, print_banner, print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "miv_dairy_companies.csv"
SOURCE_URL = "https://milchindustrie.de/ueber-uns/unsere-mitglieder/"
SOURCE_NAME = "MIV Milchindustrie-Verband Member Directory"

# This site answers the plain research user agent reliably.
USER_AGENT = "AnimalFarmingGermanyResearch/1.0"

OFFICE_TYPE = "Geschäftsstelle"
SUPPLIER_TYPE = "Firmensitz Förderer"


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def extract_record(card):
    """Turn one member card into a record, or None if not a German company."""

    def text(selector):
        # Text kept as published: company and address form the upsert key.
        return get_text(card, selector, squash=False)

    company = text(".company-name")
    location = text(".place-postcode")
    member_type = card.get("data-type", "")
    match = POSTCODE_CITY_RE.match(location)

    # Skip the association office and anything outside Germany.
    if not company or member_type == OFFICE_TYPE or not match:
        return None

    website = card.select_one(".homepage a[href]")
    categories = card.select(".categories")
    products = categories[-1].get_text(" ", strip=True) if categories else ""

    return make_record(
        company=company,
        sector=(
            "Dairy Technology and Services" if member_type == SUPPLIER_TYPE
            else "Dairy Processing and Manufacturing"
        ),
        city=match.group(2).strip(),
        postal_code=match.group(1),
        address=", ".join(p for p in (text(".street"), location) if p),
        website=website["href"].strip() if website else "",
        email=get_text(card, ".email"),
        phone=get_text(card, ".phone"),
        description=f"Directory type: {member_type}. Products: {products}",
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
    )


def collect():
    print("Opening MIV dairy directory...")
    soup = fetch_soup(SOURCE_URL, session=new_session(USER_AGENT), timeout=60)
    cards = soup.select("ul.table > li.main-li")
    print("Directory entries found:", len(cards))

    if not cards:
        raise RuntimeError("No company cards found. Website structure may have changed.")

    return dedupe(filter(None, map(extract_record, cards)))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 07: DAIRY COMPANY DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No German dairy companies extracted.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("DAIRY DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
