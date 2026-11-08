"""
STEP 03: Discover animal health companies.

Source: BfT (Bundesverband für Tiergesundheit) member directory.

The members are listed in an HTML table whose cells link to each
company's website. The page gives no addresses, so only name and
website are stored.
"""

from urllib.parse import urljoin, urlparse

from common import (
    RAW_DIR, check_count, dedupe, fetch_soup, make_record, print_banner,
    print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "animal_health_companies.csv"
SOURCE_URL = "https://www.bft-online.de/der-verband/mitglieder"
SOURCE_NAME = "BfT Member Directory"
SECTOR = "Animal Health & Veterinary Pharmaceuticals"

# Links pointing back to BfT itself are navigation, not members.
OWN_HOSTS = (None, "bft-online.de", "www.bft-online.de")

# The member table is the only table with at least this many
# external links.
MIN_MEMBER_LINKS = 15

# BfT has about 30 members; outside this range the parser is broken.
EXPECTED_COUNT = (20, 40)


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def external_links(table):
    """Links in the table's cells that leave the BfT website."""
    return [
        link for link in table.select("td a[href]")
        if urlparse(urljoin(SOURCE_URL, link["href"])).hostname not in OWN_HOSTS
    ]


def find_member_links(soup):
    """Return the website links of the one table that lists the members."""
    candidates = [
        links for links in map(external_links, soup.select("table"))
        if len(links) >= MIN_MEMBER_LINKS
    ]

    if len(candidates) != 1:
        raise RuntimeError(
            "Could not uniquely identify the BfT member table. "
            "Inspect the website structure."
        )

    return candidates[0]


def collect():
    print("Opening BfT member directory...")
    links = find_member_links(fetch_soup(SOURCE_URL, timeout=30))

    records = [
        make_record(
            company=link.get_text(" ", strip=True),
            sector=SECTOR,
            website=urljoin(SOURCE_URL, link["href"].strip()),
            source_name=SOURCE_NAME,
            source_url=SOURCE_URL,
        )
        for link in links
        if link.get_text(strip=True)
    ]

    # No addresses here, so the company name alone identifies a member.
    return dedupe(records, key=lambda r: r["company"].casefold())


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 03: ANIMAL HEALTH COMPANY DISCOVERY")

    records = collect()
    check_count(records, *EXPECTED_COUNT, SOURCE_NAME)

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("ANIMAL HEALTH DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
