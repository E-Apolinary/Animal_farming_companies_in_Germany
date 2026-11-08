"""
STEP 14: Discover commercial pig genetics companies.

Source: partner page of Schweinebesamungsstation Weser-Ems (a pig AI
station), section "ZUCHT & GENETIK" (breeding and genetics).

Each partner is a card linking to its website. The page gives no
addresses, so only name and website are stored.
"""

from common import (
    RAW_DIR, dedupe, fetch_soup, make_record, print_banner, print_summary,
    save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "pig_genetics_companies.csv"
SOURCE_URL = "https://schweinebesamung.de/ueber-uns/partner/"
SOURCE_NAME = "Weser-Ems Pig Genetics Partners"
SECTOR = "Pig Breeding and Genetics"
DESCRIPTION = (
    "Commercial pig genetics partner listed by Schweinebesamungsstation "
    "Weser-Ems. German company identity and location require verification."
)

GENETICS_HEADING = "zucht & genetik"


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def find_partner_cards(soup):
    """Partner card links of the "ZUCHT & GENETIK" section."""
    heading = next(
        (
            h for h in soup.find_all("h3")
            if h.get_text(" ", strip=True).casefold() == GENETICS_HEADING
        ),
        None,
    )

    if heading is None:
        raise RuntimeError("ZUCHT & GENETIK section not found.")

    # The cards sit in the heading's wrapper; each card's link is the
    # partner's website.
    return heading.parent.select(".sliding_box > a")


def extract_record(card):
    title = card.select_one("h4.title")
    company = title.get_text(" ", strip=True) if title else ""
    website = (card.get("href") or "").strip()

    if not company or not website:
        return None

    return make_record(
        company=company,
        sector=SECTOR,
        website=website,
        description=DESCRIPTION,
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
    )


def collect():
    print("Opening Weser-Ems partner page...")
    cards = find_partner_cards(fetch_soup(SOURCE_URL))

    # No addresses here, so the company name alone identifies a partner.
    return dedupe(filter(None, map(extract_record, cards)), key=lambda r: r["company"].casefold())


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 14: PIG GENETICS DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No pig genetics partners extracted.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("PIG GENETICS DISCOVERY REPORT", records)

    for record in records:
        print(f"  {record['company']} | {record['website']}")


if __name__ == "__main__":
    main()
