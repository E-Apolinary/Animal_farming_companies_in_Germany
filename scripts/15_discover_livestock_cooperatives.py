"""
STEP 15: Livestock cooperative discovery.

Reads the DRV (Deutscher Raiffeisenverband) organisation page, finds the
"Fachausschuss Vieh- und Fleischwirtschaft" (livestock and meat
committee), extracts the "Company, City" entries listed under it, keeps
livestock-related organisations only, and saves them to a CSV file and
to the `discovery_candidates` table of the existing project database.
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
CSV_PATH = ROOT / "data/raw/livestock_cooperatives.csv"

SOURCE_URL = "https://www.raiffeisen.de/organisation"
SOURCE_NAME = "DRV Livestock and Meat Committee"
SECTOR = "Livestock Production and Marketing"
DESCRIPTION = (
    "Livestock-related company represented on the DRV livestock and "
    "meat committee. Specific operating activities require "
    "company-level verification."
)

# Column order for both the CSV file and the database insert.
FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]

# Columns that form the table's unique key (used in ON CONFLICT).
KEY_FIELDS = ("source_name", "company", "address")

# Columns refreshed on conflict. website / email / phone are left out on
# purpose: this source has none, so existing values must not be wiped.
UPDATE_FIELDS = (
    "sector", "city", "postal_code", "description", "source_url",
    "collected_at",
)

COMMITTEE_HEADING = "fachausschuss vieh- und fleischwirtschaft"
HEADING_RE = re.compile(r"^h[1-6]$")

# Longer "cities" are leftover page text, not real locations.
MAX_CITY_LENGTH = 90

# Characters trimmed from both ends of company and city names.
STRIP_CHARS = " |–-"


# --------------------------------------------------
# RELEVANCE FILTER
# --------------------------------------------------

# Keep organizations directly involved in livestock
# breeding, production, collection or marketing.
INCLUDE_TERMS = (
    "vieh", "rinderzucht", "fleischvermarktung", "erzeugergemeinschaft",
    "westfleisch", "agri v raiffeisen",
)

# Exclude general-purpose associations and suppliers.
EXCLUDE_TERMS = (
    "genossenschaftsverband", "raiffeisenverband", "genoverband",
    "landwirtschaftskammer", "akademie", "bank",
)

# Committee roles appended to some entries, e.g. "Firma, Ort Vorsitzender".
# Longer forms come first so "Stellv. Vorsitzender" is removed whole.
ROLE_SUFFIXES = (
    "Stellv. Vorsitzender", "Stellv. Vorsitzende",
    "Vorsitzender", "Vorsitzende",
)


def is_relevant_company(name):
    """True if the name matches a livestock term and no excluded term."""
    value = name.casefold()

    if any(term in value for term in EXCLUDE_TERMS):
        return False

    return any(term in value for term in INCLUDE_TERMS)


# --------------------------------------------------
# DOWNLOAD OFFICIAL DIRECTORY
# --------------------------------------------------

def download_directory():
    """Download the DRV organisation page and parse it as HTML."""
    print("Opening DRV organization directory...")

    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AnimalFarmingGermany/1.0)"},
        timeout=45,
    )
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


# --------------------------------------------------
# EXTRACT LIVESTOCK COMMITTEE SECTION
# --------------------------------------------------

def extract_committee_text(soup):
    """
    Locate the livestock-and-meat committee heading, then return the
    text lines that follow it, up to the next committee heading.
    """
    heading = next(
        (
            h for h in soup.find_all(HEADING_RE)
            if COMMITTEE_HEADING in h.get_text(" ", strip=True).casefold()
        ),
        None,
    )

    if heading is None:
        raise RuntimeError(
            "Livestock committee heading not found. "
            "The website structure may have changed."
        )

    lines = []

    # next_elements walks every tag and text node after the heading in
    # document order, so the section is read regardless of nesting.
    for element in heading.next_elements:

        # Stop at the next committee's h1/h2 heading.
        if getattr(element, "name", None) in ("h1", "h2"):
            title = element.get_text(" ", strip=True)

            if "Fachausschuss" in title and "Vieh- und Fleischwirtschaft" not in title:
                break

        # Read text nodes only; reading tags would repeat their children's text.
        if isinstance(element, str):
            value = " ".join(element.split())

            if value:
                lines.append(value)

    if not lines:
        raise RuntimeError("Committee found but no content extracted.")

    return lines


# --------------------------------------------------
# PARSE COMPANIES
# --------------------------------------------------

def clean_role_suffix(text):
    """Remove a trailing committee role such as 'Vorsitzender'."""
    for suffix in ROLE_SUFFIXES:
        if text.endswith(suffix):
            text = text.removesuffix(suffix).strip()

    return text


def extract_companies(lines):
    """Turn 'Company, City' lines into unique, relevant records."""
    records = []
    seen = set()  # (company, city) pairs already collected

    # One timestamp for the whole run, so all records share it.
    collected_at = datetime.now(timezone.utc).isoformat()

    for line in lines:
        line = clean_role_suffix(line)

        # Committee entries look like "Company Name, City".
        if "," not in line:
            continue

        # Split on the last comma: company names may contain commas.
        company, city = (part.strip(STRIP_CHARS) for part in line.rsplit(",", 1))

        if (
            not company
            or not city
            or len(city) > MAX_CITY_LENGTH
            or not is_relevant_company(company)
        ):
            continue

        key = (company.casefold(), city.casefold())

        if key in seen:
            continue

        seen.add(key)
        records.append({
            "company": company,
            "sector": SECTOR,
            "city": city,
            "postal_code": "",
            "address": city,  # only the city is published
            "website": "",
            "email": "",
            "phone": "",
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
# UPSERT INTO EXISTING DATABASE
# --------------------------------------------------

def save_database(records):
    """
    Insert records, or update them if they already exist.

    The SQL is built from FIELDS / KEY_FIELDS / UPDATE_FIELDS. Named
    placeholders (:company, ...) let sqlite read values straight from
    each record dict, and executemany sends all rows in one call.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Existing database not found: {DB_PATH}")

    columns = ", ".join(FIELDS)
    placeholders = ", ".join(f":{field}" for field in FIELDS)
    updates = ", ".join(f"{field} = excluded.{field}" for field in UPDATE_FIELDS)

    with sqlite3.connect(DB_PATH) as conn:

        # Make sure this is the established project database.
        table = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'discovery_candidates'"
        ).fetchone()

        if table is None:
            raise RuntimeError("discovery_candidates table not found.")

        conn.executemany(
            f"""
            INSERT INTO discovery_candidates ({columns})
            VALUES ({placeholders})
            ON CONFLICT ({", ".join(KEY_FIELDS)})
            DO UPDATE SET {updates}
            """,
            records,
        )

    print("Existing database updated successfully.")


# --------------------------------------------------
# REPORT
# --------------------------------------------------

def report(records):
    """Print a summary and the list of discovered organisations."""
    print()
    print("=" * 45)
    print("LIVESTOCK COOPERATIVES DISCOVERY REPORT")
    print("=" * 45)
    print("Company/location records:", len(records))
    print("Unique company names:", len({r["company"].casefold() for r in records}))

    print()
    print("Discovered organizations:")

    for record in sorted(records, key=lambda r: r["company"].casefold()):
        print(f"  {record['company']} ({record['city']})")

    print("=" * 45)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 15: LIVESTOCK COOPERATIVE DISCOVERY")
    print("=" * 45)

    lines = extract_committee_text(download_directory())
    records = extract_companies(lines)

    if not records:
        raise RuntimeError(
            "No relevant organizations extracted. Database was not changed."
        )

    save_csv(records)
    save_database(records)
    report(records)


if __name__ == "__main__":
    main()
