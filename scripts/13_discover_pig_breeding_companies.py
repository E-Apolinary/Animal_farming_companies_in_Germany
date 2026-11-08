"""
STEP 13: Discover pig breeding organisations.

Source: FBF (Förderverein Biotechnologieforschung) member page, section
"Tierart SCHWEIN" (pigs).

Each member is a block of text lines: company name (one or more lines),
street, "12345 City", then contact lines. Only German members (five-digit
postcode) are kept.
"""

import re

from common import (
    EMAIL_RE, POSTCODE_CITY_RE, RAW_DIR, clean, dedupe, fetch_soup,
    make_record, normalize_website, print_banner, print_summary, save_csv,
    save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "pig_breeding_companies.csv"
SOURCE_URL = "https://www.fbf-forschung.de/fbf-mitglieder.html"
SOURCE_NAME = "FBF Pig Breeding Member Directory"
SECTOR = "Pig Breeding and Genetics"
DESCRIPTION = "FBF member listed in the pig breeding and reproduction section."

PIG_HEADING = "tierart schwein"

# Member entries are <div> blocks carrying both of these classes.
BLOCK_CLASSES = ("flex_cols", "flex_nowrap")

# The page shows this member under its brand; store the legal name.
GERMAN_GENETIC_PREFIX = "German Genetic Schweinezuchtverband"
GERMAN_GENETIC_NAME = "Schweinezuchtverband Baden-Württemberg e.V."

# Foreign members whose address format could slip past the postcode check.
FOREIGN_TERMS = ("austria", "suisag", "österreichischer")

PHONE_RE = re.compile(r"^(tel\.?|telefon)\s*:?\s*", re.IGNORECASE)


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def find_pig_blocks(soup):
    """
    Member blocks of the pig section.

    The page splits members with <h1> headings (Tierart Rind, Tierart
    SCHWEIN, Leistungs- und Qualitätsprüfung). The member blocks are the
    siblings that follow the pig heading's container.
    """
    heading = next(
        (h for h in soup.find_all("h1") if clean(h.get_text()).casefold() == PIG_HEADING),
        None,
    )

    if heading is None:
        raise RuntimeError("FBF pig member section not found.")

    blocks = []

    for sibling in heading.parent.find_next_siblings():
        if sibling.find("h1"):  # next section reached
            break

        if all(name in sibling.get("class", []) for name in BLOCK_CLASSES):
            blocks.append(sibling)

    return blocks


def extract_phone(lines):
    """Number from the first 'Tel.:' / 'Telefon:' line, or ''."""
    for line in lines:
        if match := PHONE_RE.match(line):
            return line[match.end():].strip()

    return ""


def extract_website(block, lines):
    """Website from the block's links, else from a 'www.' text line."""
    for link in block.select("a[href]"):
        href = link["href"].strip()

        if href.startswith("mailto:"):
            continue
        if href.startswith(("http://", "https://")):
            return href

        # Some links are relative; their text shows the domain.
        if website := normalize_website(link.get_text(" ", strip=True)):
            return website

    return next((normalize_website(line) for line in lines if line.startswith("www.")), "")


def extract_record(block):
    """Turn one member block into a record, or None if not German."""
    lines = [line for line in map(clean, block.get_text("\n", strip=True).splitlines()) if line]

    # The "12345 City" line; Austria and Switzerland use four digits.
    index, match = next(
        ((i, m) for i, line in enumerate(lines) if (m := POSTCODE_CITY_RE.match(line))),
        (None, None),
    )

    # Company and street lines must come before the location line.
    if index is None or index < 2:
        return None

    company = " ".join(lines[:index - 1])
    street = lines[index - 1]
    postal_code, city = match.group(1), clean(match.group(2))

    if company.startswith(GERMAN_GENETIC_PREFIX):
        company = GERMAN_GENETIC_NAME

    if any(term in company.casefold() for term in FOREIGN_TERMS):
        return None

    return make_record(
        company=company,
        sector=SECTOR,
        city=city,
        postal_code=postal_code,
        address=f"{street} | {postal_code} {city}",
        website=extract_website(block, lines),
        email=(m.group(0) if (m := EMAIL_RE.search(" ".join(lines))) else ""),
        phone=extract_phone(lines),
        description=DESCRIPTION,
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
    )


def collect():
    print("Opening FBF member directory...")
    blocks = find_pig_blocks(fetch_soup(SOURCE_URL))
    print("Pig directory entries:", len(blocks))

    return dedupe(filter(None, map(extract_record, blocks)))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 13: PIG BREEDING DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No German pig breeding companies extracted.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("PIG BREEDING DISCOVERY REPORT", records)

    for record in records:
        print(f"  {record['company']} ({record['city']})")


if __name__ == "__main__":
    main()
