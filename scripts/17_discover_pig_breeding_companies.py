"""
STEP 17: Pig breeding company discovery.

Reads the FBF (Förderverein Biotechnologieforschung) member page, finds the
"Tierart SCHWEIN" (pig) section, parses each member block into company,
address and contact details, keeps German members only, and saves them
to a CSV file and to the `discovery_candidates` table of the existing
project database.
"""

import csv
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
CSV_PATH = ROOT / "data/raw/pig_breeding_companies.csv"

SOURCE_URL = "https://www.fbf-forschung.de/fbf-mitglieder.html"
SOURCE_NAME = "FBF Pig Breeding Member Directory"
SECTOR = "Pig Breeding and Genetics"
DESCRIPTION = "FBF member listed in the pig breeding and reproduction section."

# Column order for both the CSV file and the database insert.
FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]

# Columns that form the table's unique key (used in ON CONFLICT).
KEY_FIELDS = ("source_name", "company", "address")

# Columns always overwritten on conflict.
UPDATE_FIELDS = (
    "sector", "city", "postal_code", "description", "source_url",
    "collected_at",
)

# Columns overwritten only when the new value is not empty, so a blank
# entry on the page never wipes a value already stored.
KEEP_IF_EMPTY_FIELDS = ("website", "email", "phone")

# Heading of the pig section on the FBF page.
PIG_HEADING = "tierart schwein"

# Member entries are <div> blocks carrying both of these classes.
BLOCK_CLASSES = ("flex_cols", "flex_nowrap")

# The page shows this member under its brand name; store the legal name.
GERMAN_GENETIC_PREFIX = "German Genetic Schweinezuchtverband"
GERMAN_GENETIC_NAME = "Schweinezuchtverband Baden-Württemberg e.V."

# Foreign members whose address format could slip through the
# postcode check.
FOREIGN_TERMS = ("austria", "suisag", "österreichischer")

# Compiled once instead of on every block / line.
LOCATION_RE = re.compile(r"^(\d{5})\s+(.+)$")
PHONE_RE = re.compile(r"^(tel\.?|telefon)\s*:?\s*", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
DOMAIN_RE = re.compile(r"^[^\s@]+\.[a-zA-Z]{2,}")


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def clean(value):
    """Collapse all whitespace to single spaces; None becomes ''."""
    return " ".join(str(value or "").split())


def normalize_website(value):
    """Turn '//x.de', 'www.x.de' or 'x.de' into a full https URL, else ''."""
    value = clean(value)

    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("www.") or DOMAIN_RE.match(value):
        return "https://" + value

    return ""


def extract_email(text):
    """Return the first email address found in text, or ''."""
    match = EMAIL_RE.search(text)
    return match.group(0) if match else ""


def extract_phone(lines):
    """Return the number from the first 'Tel.:' / 'Telefon:' line, or ''."""
    for line in lines:
        match = PHONE_RE.match(line)

        if match:
            return line[match.end():].strip()

    return ""


def extract_website(block, lines):
    """Find the website from the block's links, else from a 'www.' line."""
    for link in block.select("a[href]"):
        href = link["href"].strip()

        if href.startswith("mailto:"):
            continue
        if href.startswith(("http://", "https://")):
            return href

        # Some links are relative and only their text shows the domain.
        website = normalize_website(link.get_text(" ", strip=True))

        if website:
            return website

    return next(
        (normalize_website(line) for line in lines if line.startswith("www.")),
        "",
    )


# --------------------------------------------------
# DOWNLOAD
# --------------------------------------------------

def download_directory():
    """Download the FBF member page and parse it as HTML."""
    print("Opening FBF member directory...")

    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AnimalFarmingGermany/1.0)"},
        timeout=45,
    )
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


# --------------------------------------------------
# FIND PIG MEMBER BLOCKS
# --------------------------------------------------

def find_pig_blocks(soup):
    """
    Return the member blocks of the pig section.

    The page splits its members with <h1> headings:

        Tierart Rind
        Tierart SCHWEIN
        Leistungs- und Qualitätsprüfung

    Member entries are div.flex_cols.flex_nowrap blocks that are
    siblings of the heading's container.
    """
    heading = next(
        (h for h in soup.find_all("h1") if clean(h.get_text()).casefold() == PIG_HEADING),
        None,
    )

    if heading is None:
        raise RuntimeError("FBF pig member section not found.")

    blocks = []

    # Walk forward through the siblings until the next section's <h1>.
    for current in heading.parent.find_next_siblings():
        if current.find("h1"):
            break

        classes = current.get("class", [])

        if all(name in classes for name in BLOCK_CLASSES):
            blocks.append(current)

    return blocks


# --------------------------------------------------
# EXTRACT COMPANIES
# --------------------------------------------------

def parse_location(lines):
    """
    Find the first "12345 City" line.

    Returns (index, postal_code, city), or None when there is no German
    five-digit postcode (Austria and Switzerland use four digits).
    """
    for index, line in enumerate(lines):
        match = LOCATION_RE.match(line)

        if match:
            return index, match.group(1), clean(match.group(2))

    return None


def extract_companies(blocks):
    """Parse each member block into a unique German company record."""
    records = []
    seen = set()  # (company, address) pairs already collected

    # One timestamp for the whole run, so all records share it.
    collected_at = datetime.now(timezone.utc).isoformat()

    for block in blocks:
        # One cleaned, non-empty string per visible line of the block.
        lines = [
            line
            for line in map(clean, block.get_text("\n", strip=True).splitlines())
            if line
        ]

        location = parse_location(lines)

        # A block needs at least a company line and a street line above
        # the "12345 City" line.
        if location is None or location[0] < 2:
            continue

        index, postal_code, city = location

        # Layout: company name (one or more lines), street, "12345 City".
        company = " ".join(lines[:index - 1])
        street = lines[index - 1]

        if company.startswith(GERMAN_GENETIC_PREFIX):
            company = GERMAN_GENETIC_NAME

        if any(term in company.casefold() for term in FOREIGN_TERMS):
            continue

        address = f"{street} | {postal_code} {city}"
        key = (company.casefold(), address.casefold())

        if key in seen:
            continue

        seen.add(key)
        records.append({
            "company": company,
            "sector": SECTOR,
            "city": city,
            "postal_code": postal_code,
            "address": address,
            "website": extract_website(block, lines),
            "email": extract_email(" ".join(lines)),
            "phone": extract_phone(lines),
            "description": DESCRIPTION,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "collected_at": collected_at,
        })

    return records


# --------------------------------------------------
# SAVE CSV
# --------------------------------------------------

def save_csv(records):
    """Write records to CSV (utf-8-sig so Excel shows umlauts correctly)."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    print("CSV saved:", CSV_PATH)


# --------------------------------------------------
# SAVE TO EXISTING DATABASE
# --------------------------------------------------

def save_database(records):
    """
    Insert records, or update them if they already exist.

    The SQL is built from the field lists above. Named placeholders
    (:company, ...) let sqlite read values straight from each record
    dict, and executemany sends all rows in one call.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    columns = ", ".join(FIELDS)
    placeholders = ", ".join(f":{field}" for field in FIELDS)
    updates = ", ".join(
        [f"{field} = excluded.{field}" for field in UPDATE_FIELDS]
        + [
            f"{field} = CASE WHEN excluded.{field} != '' "
            f"THEN excluded.{field} ELSE discovery_candidates.{field} END"
            for field in KEEP_IF_EMPTY_FIELDS
        ]
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            f"""
            INSERT INTO discovery_candidates ({columns})
            VALUES ({placeholders})
            ON CONFLICT ({", ".join(KEY_FIELDS)})
            DO UPDATE SET {updates}
            """,
            records,
        )

    print("Database updated successfully.")


# --------------------------------------------------
# REPORT
# --------------------------------------------------

def print_report(records):
    """Print data completeness and the list of discovered companies."""

    def count(field):
        return sum(bool(r[field]) for r in records)

    print()
    print("=" * 45)
    print("PIG BREEDING DISCOVERY REPORT")
    print("=" * 45)
    print("German companies:", len(records))
    print("With websites:", count("website"))
    print("With emails:", count("email"))
    print("With phones:", count("phone"))

    print()
    print("Discovered companies:")

    for record in records:
        print(f"  {record['company']} ({record['city']})")

    print("=" * 45)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 17: PIG BREEDING DISCOVERY")
    print("=" * 45)

    blocks = find_pig_blocks(download_directory())
    print("Pig directory entries:", len(blocks))

    records = extract_companies(blocks)

    if not records:
        raise RuntimeError("No German pig breeding companies extracted.")

    save_csv(records)
    save_database(records)
    print_report(records)


if __name__ == "__main__":
    main()
