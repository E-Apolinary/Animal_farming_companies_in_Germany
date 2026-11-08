"""
STEP 11: Discover livestock cooperatives.

Source: DRV (Deutscher Raiffeisenverband) organisation page, section
"Fachausschuss Vieh- und Fleischwirtschaft" (livestock and meat
committee).

The committee lists its members as "Company, City" lines. Only
organisations directly involved in livestock breeding, production or
marketing are kept; banks and general associations are filtered out.
"""

import re

from common import (
    RAW_DIR, dedupe, fetch_soup, make_record, print_banner, print_summary,
    save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "livestock_cooperatives.csv"
SOURCE_URL = "https://www.raiffeisen.de/organisation"
SOURCE_NAME = "DRV Livestock and Meat Committee"
SECTOR = "Livestock Production and Marketing"
DESCRIPTION = (
    "Livestock-related company represented on the DRV livestock and meat "
    "committee. Specific operating activities require company-level verification."
)

COMMITTEE_HEADING = "fachausschuss vieh- und fleischwirtschaft"
HEADING_RE = re.compile(r"^h[1-6]$")

# Longer "cities" are leftover page text, not real locations.
MAX_CITY_LENGTH = 90

# Characters trimmed from both ends of company and city names.
STRIP_CHARS = " |–-"

# Keep organisations directly involved in livestock breeding,
# production, collection or marketing...
INCLUDE_TERMS = (
    "vieh", "rinderzucht", "fleischvermarktung", "erzeugergemeinschaft",
    "westfleisch", "agri v raiffeisen",
)

# ...but not general associations, chambers, academies or banks.
EXCLUDE_TERMS = (
    "genossenschaftsverband", "raiffeisenverband", "genoverband",
    "landwirtschaftskammer", "akademie", "bank",
)

# Committee roles appended to some entries, e.g. "Firma, Ort Vorsitzender".
# Longer forms first, so "Stellv. Vorsitzender" is removed whole.
ROLE_SUFFIXES = (
    "Stellv. Vorsitzender", "Stellv. Vorsitzende", "Vorsitzender", "Vorsitzende",
)


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def is_relevant(name):
    """True if the name matches a livestock term and no excluded term."""
    value = name.casefold()
    return (
        not any(term in value for term in EXCLUDE_TERMS)
        and any(term in value for term in INCLUDE_TERMS)
    )


def committee_lines(soup):
    """Text lines after the committee heading, up to the next committee."""
    heading = next(
        (
            h for h in soup.find_all(HEADING_RE)
            if COMMITTEE_HEADING in h.get_text(" ", strip=True).casefold()
        ),
        None,
    )

    if heading is None:
        raise RuntimeError(
            "Livestock committee heading not found. The website structure may have changed."
        )

    lines = []

    # next_elements walks every tag and text node after the heading in
    # document order, so the section is read regardless of nesting.
    for element in heading.next_elements:
        if getattr(element, "name", None) in ("h1", "h2"):
            title = element.get_text(" ", strip=True)

            if "Fachausschuss" in title and "Vieh- und Fleischwirtschaft" not in title:
                break

        # Text nodes only; reading tags would repeat their children's text.
        if isinstance(element, str) and (value := " ".join(element.split())):
            lines.append(value)

    if not lines:
        raise RuntimeError("Committee found but no content extracted.")

    return lines


def strip_role(text):
    for suffix in ROLE_SUFFIXES:
        if text.endswith(suffix):
            text = text.removesuffix(suffix).strip()

    return text


def extract_record(line):
    """Turn a "Company, City" line into a record, or None."""
    line = strip_role(line)

    if "," not in line:
        return None

    # Split on the last comma: company names may contain commas.
    company, city = (part.strip(STRIP_CHARS) for part in line.rsplit(",", 1))

    if not company or not city or len(city) > MAX_CITY_LENGTH or not is_relevant(company):
        return None

    return make_record(
        company=company,
        sector=SECTOR,
        city=city,
        address=city,  # only the city is published
        description=DESCRIPTION,
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
    )


def collect():
    print("Opening DRV organisation directory...")
    lines = committee_lines(fetch_soup(SOURCE_URL))
    return dedupe(filter(None, map(extract_record, lines)))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 11: LIVESTOCK COOPERATIVE DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No relevant organisations extracted. Database was not changed.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("LIVESTOCK COOPERATIVES REPORT", records)

    for record in sorted(records, key=lambda r: r["company"].casefold()):
        print(f"  {record['company']} ({record['city']})")


if __name__ == "__main__":
    main()
