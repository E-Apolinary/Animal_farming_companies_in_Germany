"""
STEP 16: Cattle breeding company discovery.

Reads the ASR (Arbeitsgemeinschaft Süddeutscher Rinderzüchter und
Besamungsorganisationen) member directory. The page is a set of HTML
table rows in which category headings (breeding associations, AI
stations, ...) are followed by member rows. Each member is tagged with
the sector of its category and saved to a CSV file and to the
`discovery_candidates` table of the existing project database.
"""

import csv
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
CSV_PATH = ROOT / "data/raw/cattle_breeding_companies.csv"

SOURCE_URL = "https://www.asr-rind.de/ueber-uns/mitglieder.html"
SOURCE_NAME = "ASR Cattle Breeding Member Directory"

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
# cell on the page never wipes a value already stored. phone is in
# neither list because this source does not publish phone numbers.
KEEP_IF_EMPTY_FIELDS = ("website", "email")

# Directory category heading -> project sector.
SECTORS = {
    "Zuchtverbände": "Cattle Breeding",
    "Besamungsstationen": "Cattle Genetics and Reproduction",
    "Zucht- und Besamungsorganisationen": "Cattle Breeding and Genetics",
}

# Member rows have exactly five columns:
# organisation, postcode, city, email, website.
MEMBER_COLUMNS = 5

# Already covered as a dairy processor; excluded from this phase.
EXCLUDED_PREFIX = "privatmolkerei bauer"

# Compiled once instead of on every row.
POSTCODE_RE = re.compile(r"\d{5}")
DOMAIN_RE = re.compile(r"^[^\s@]+\.[a-zA-Z]{2,}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def clean(value):
    """Collapse all whitespace to single spaces; None becomes ''."""
    return " ".join(str(value or "").split())


def normalize_website(value):
    """Turn '//x.de', 'www.x.de' or 'x.de' into a full https URL, else ''."""
    value = clean(value)

    if value.startswith(("https://", "http://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("www.") or DOMAIN_RE.match(value):
        return "https://" + value

    return ""


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
    """Read the address from a mailto: link, or find one in the text."""
    link = cell.select_one("a[href^='mailto:']")

    if link:
        # "mailto:info@x.de?subject=..." -> "info@x.de"
        return clean(link["href"].removeprefix("mailto:").split("?")[0])

    match = EMAIL_RE.search(clean(cell.get_text(" ", strip=True)))
    return match.group(0) if match else ""


# --------------------------------------------------
# DOWNLOAD DIRECTORY
# --------------------------------------------------

def download_directory():
    """Download the ASR member page and parse it as HTML."""
    print("Opening ASR member directory...")

    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AnimalFarmingGermany/1.0)"},
        timeout=45,
    )
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


# --------------------------------------------------
# EXTRACT ORGANIZATIONS
# --------------------------------------------------

def extract_companies(soup):
    """Walk the table rows and build one record per member."""
    records = []
    seen = set()  # (company, city) pairs already collected
    category = ""  # category heading the current rows belong to

    # One timestamp for the whole run, so all records share it.
    collected_at = datetime.now(timezone.utc).isoformat()

    # Category headings and member rows sit in the same table, so the
    # last heading seen tells us which sector the following rows have.
    for row in soup.select("tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        values = [clean(cell.get_text(" ", strip=True)) for cell in cells]

        # A row containing a category name switches the current category.
        category = next((v for v in values if v in SECTORS), category)

        # Skip rows before the first category and non-member rows.
        if category not in SECTORS or len(cells) != MEMBER_COLUMNS:
            continue

        company, postal_code, city = values[:3]
        name = company.casefold()

        # Skip empty rows, the table's header row and excluded members.
        if (
            not company
            or not city
            or name == "organisation"
            or name.startswith(EXCLUDED_PREFIX)
        ):
            continue

        key = (name, city.casefold())

        if key in seen:
            continue

        seen.add(key)

        # Keep only valid German postcodes. A bad value is blanked, not
        # replaced with a guess.
        if not POSTCODE_RE.fullmatch(postal_code):
            postal_code = ""

        records.append({
            "company": company,
            "sector": SECTORS[category],
            "city": city,
            "postal_code": postal_code,
            "address": f"{postal_code} {city}".strip(),
            "website": extract_website(cells[4]),
            "email": extract_email(cells[3]),
            "phone": "",
            "description": f"ASR member listed under {category}.",
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

    print("Database updated successfully.")


# --------------------------------------------------
# REPORT
# --------------------------------------------------

def print_report(records):
    """Print data completeness and the number of records per sector."""

    def count(field):
        return sum(bool(r[field]) for r in records)

    print()
    print("=" * 45)
    print("CATTLE BREEDING DISCOVERY REPORT")
    print("=" * 45)
    print("Total records:", len(records))
    print("Unique company names:", len({r["company"].casefold() for r in records}))
    print("Companies with websites:", count("website"))
    print("Companies with emails:", count("email"))
    print("Companies with cities:", count("city"))

    print()
    print("Sector distribution:")

    # Counter counts every sector in a single pass over the records.
    for sector, total in sorted(Counter(r["sector"] for r in records).items()):
        print(f"  {sector}: {total}")

    print("=" * 45)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 16: CATTLE BREEDING DISCOVERY")
    print("=" * 45)

    records = extract_companies(download_directory())

    if not records:
        raise RuntimeError(
            "No cattle breeding companies extracted. Database was not modified."
        )

    save_csv(records)
    save_database(records)
    print_report(records)


if __name__ == "__main__":
    main()
