"""
STEP 12: Discover cattle breeding and genetics organisations.

Source: ASR (Arbeitsgemeinschaft Süddeutscher Rinderzüchter und
Besamungsorganisationen) member directory.

The page is one set of table rows in which category headings (breeding
associations, AI stations, ...) are followed by member rows. Each member
gets the sector of the category it is listed under.
"""

from collections import Counter

from common import (
    EMAIL_RE, POSTCODE_RE, RAW_DIR, clean, dedupe, fetch_soup, make_record,
    mailto_address, normalize_website, print_banner, print_summary,
    save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "cattle_breeding_companies.csv"
SOURCE_URL = "https://www.asr-rind.de/ueber-uns/mitglieder.html"
SOURCE_NAME = "ASR Cattle Breeding Member Directory"

# Directory category heading -> project sector.
SECTORS = {
    "Zuchtverbände": "Cattle Breeding",
    "Besamungsstationen": "Cattle Genetics and Reproduction",
    "Zucht- und Besamungsorganisationen": "Cattle Breeding and Genetics",
}

# Member rows: organisation, postcode, city, email, website.
MEMBER_COLUMNS = 5

# Already covered as a dairy processor (step 07).
EXCLUDED_PREFIX = "privatmolkerei bauer"


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def extract_website(cell):
    """Prefer a real http(s) link; otherwise read the link or cell text."""
    link = cell.find("a", href=True)

    if link is None:
        return normalize_website(cell.get_text(" ", strip=True))

    href = link["href"].strip()

    if href.startswith(("http://", "https://")):
        return href

    return normalize_website(link.get_text(" ", strip=True))


def extract_email(cell):
    """Address from a mailto: link, or the first address in the text."""
    link = cell.select_one("a[href^='mailto:']")

    if link:
        return clean(mailto_address(link["href"]))

    match = EMAIL_RE.search(clean(cell.get_text(" ", strip=True)))
    return match.group(0) if match else ""


def collect():
    """Walk the table rows and build one record per member."""
    print("Opening ASR member directory...")
    records = []
    category = ""  # category heading the current rows belong to

    # The last category heading seen applies to the rows below it.
    for row in fetch_soup(SOURCE_URL).select("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        values = [clean(cell.get_text(" ", strip=True)) for cell in cells]
        category = next((v for v in values if v in SECTORS), category)

        if category not in SECTORS or len(cells) != MEMBER_COLUMNS:
            continue

        company, postal_code, city = values[:3]
        name = company.casefold()

        # Skip empty rows, the table header and excluded members.
        if not company or not city or name == "organisation" or name.startswith(EXCLUDED_PREFIX):
            continue

        # Blank a malformed postcode rather than guess one.
        if not POSTCODE_RE.fullmatch(postal_code):
            postal_code = ""

        records.append(make_record(
            company=company,
            sector=SECTORS[category],
            city=city,
            postal_code=postal_code,
            address=f"{postal_code} {city}".strip(),
            website=extract_website(cells[4]),
            email=extract_email(cells[3]),
            description=f"ASR member listed under {category}.",
            source_name=SOURCE_NAME,
            source_url=SOURCE_URL,
        ))

    return dedupe(records, key=lambda r: (r["company"].casefold(), r["city"].casefold()))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 12: CATTLE BREEDING DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No cattle breeding companies extracted. Database was not modified.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("CATTLE BREEDING DISCOVERY REPORT", records)

    print("Sector distribution:")

    for sector, total in sorted(Counter(r["sector"] for r in records).items()):
        print(f"  {sector}: {total}")


if __name__ == "__main__":
    main()
