"""
STEP 02: Discover animal feed and nutrition companies.

Source: DVT (Deutscher Verband Tiernahrung) member directory.

Each member is an <h3> heading followed by paragraphs: the first one is
the address, the rest describe the company. German members are kept
and saved to data/raw/dvt_companies.csv and to discovery_candidates.
"""

import re

from bs4 import Tag

from common import (
    RAW_DIR, dedupe, fetch_soup, make_record, mailto_address,
    print_banner, print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "dvt_companies.csv"
SOURCE_URL = "https://www.dvtiernahrung.de/ueber-uns/unsere-mitglieder"
SOURCE_NAME = "DVT Member Directory"
SECTOR = "Animal Feed and Nutrition"

# "... 12345 City ..." anywhere in the address paragraph.
POSTCODE_CITY_RE = re.compile(r"\b(\d{5})\s+([^\n]+)")

# The address paragraph often runs on into "Tel: ..." or "zur Website";
# the city ends where one of these starts.
CITY_END_RE = re.compile(
    r"\s+(?:Tel\.?|Telefon|zur Website|Website)\b|\s+\+49\b",
    re.IGNORECASE,
)

PHONE_RE = re.compile(r"(?:Tel\.?|Telefon)\s*:?\s*(\+?[\d\s()/.-]{6,})", re.IGNORECASE)

# Members whose address names one of these countries are not German.
FOREIGN_COUNTRIES = (
    "österreich", "austria", "frankreich", "france", "niederlande",
    "netherlands", "belgien", "belgium", "schweiz", "switzerland",
    "italien", "italy", "polen", "poland", "dänemark", "denmark",
    "spanien", "spain",
)


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def read_profile(heading):
    """Collect paragraphs, first website and first email up to the next <h3>."""
    paragraphs, website, email = [], "", ""

    # next_elements walks every tag after the heading in document order.
    for element in heading.next_elements:
        if not isinstance(element, Tag):
            continue
        if element.name == "h3":
            break

        if element.name == "p":
            text = element.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)

        elif element.name == "a":
            href = element.get("href", "").strip()

            if href.startswith("mailto:") and not email:
                email = mailto_address(href)
            elif href.startswith(("http://", "https://")) and not website:
                website = href

    return paragraphs, website, email


def extract_record(heading):
    """Turn one member heading into a record, or None if not German."""
    company = heading.get_text(" ", strip=True)

    if not company:
        return None

    paragraphs, website, email = read_profile(heading)

    if not paragraphs:
        return None

    # Profiles start with the address paragraph.
    address = paragraphs[0]
    match = POSTCODE_CITY_RE.search(address)

    if not match or any(country in address.lower() for country in FOREIGN_COUNTRIES):
        return None

    city = CITY_END_RE.split(match.group(2), maxsplit=1)[0].strip(" ,;")

    phone = next(
        (m.group(1).strip() for p in paragraphs if (m := PHONE_RE.search(p))),
        "",
    )

    return make_record(
        company=company,
        sector=SECTOR,
        city=city,
        postal_code=match.group(1),
        address=address,
        website=website,
        email=email,
        phone=phone,
        # Keep the full profile text so no detail is lost.
        description=" | ".join(paragraphs[1:]),
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
    )


def collect():
    print("Opening DVT member directory...")
    headings = fetch_soup(SOURCE_URL).find_all("h3")
    print("Directory headings found:", len(headings))

    return dedupe(filter(None, map(extract_record, headings)))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 02: FEED COMPANY DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No DVT companies extracted. The website structure may have changed.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("FEED COMPANY DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
