"""
STEP 18: Pig genetics company discovery.

Reads the partner page of Schweinebesamungsstation Weser-Ems, finds the
"ZUCHT & GENETIK" (breeding and genetics) section, and collects the
name and website of each partner card. The page gives no address, so
location fields stay empty. Results are saved to a CSV file and to the
`discovery_candidates` table of the existing project database.
"""

import csv
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
CSV_PATH = ROOT / "data/raw/pig_genetics_companies.csv"

SOURCE_URL = "https://schweinebesamung.de/ueber-uns/partner/"
SOURCE_NAME = "Weser-Ems Pig Genetics Partners"
SECTOR = "Pig Breeding and Genetics"
DESCRIPTION = (
    "Commercial pig genetics partner listed by Schweinebesamungsstation "
    "Weser-Ems. German company identity and location require verification."
)

# Column order for both the CSV file and the database insert.
FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]

# Columns that form the table's unique key (used in ON CONFLICT).
KEY_FIELDS = ("source_name", "company", "address")

# Columns refreshed on conflict. Location and contact columns are left
# out on purpose: this source has none, so stored values must not be
# wiped by its empty ones.
UPDATE_FIELDS = ("sector", "website", "description", "source_url", "collected_at")

# Heading of the genetics section on the partner page.
GENETICS_HEADING = "zucht & genetik"


# --------------------------------------------------
# DOWNLOAD DIRECTORY
# --------------------------------------------------

def download_directory():
    """Download the partner page and parse it as HTML."""
    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AnimalFarmingGermany/1.0)"},
        timeout=45,
    )
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


# --------------------------------------------------
# EXTRACT GENETICS PARTNERS
# --------------------------------------------------

def find_genetics_cards(soup):
    """Return the partner card links of the "ZUCHT & GENETIK" section."""
    heading = next(
        (
            h for h in soup.find_all("h3")
            if h.get_text(" ", strip=True).casefold() == GENETICS_HEADING
        ),
        None,
    )

    if heading is None:
        raise RuntimeError("ZUCHT & GENETIK section not found.")

    # The partner cards sit in the same wrapper as the heading. Each card
    # is a link whose href is the partner's website.
    return heading.parent.select(".sliding_box > a")


def extract_companies(soup):
    """Build one record per partner card that has a name and a website."""
    records = []
    seen = set()  # company names already collected

    # One timestamp for the whole run, so all records share it.
    collected_at = datetime.now(timezone.utc).isoformat()

    for card in find_genetics_cards(soup):
        title = card.select_one("h4.title")

        if title is None:
            continue

        company = title.get_text(" ", strip=True)
        website = (card.get("href") or "").strip()

        if not company or not website or company.casefold() in seen:
            continue

        seen.add(company.casefold())
        records.append({
            "company": company,
            "sector": SECTOR,
            "city": "",
            "postal_code": "",
            "address": "",
            "website": website,
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
# SAVE INTO EXISTING DATABASE
# --------------------------------------------------

def save_database(records):
    """
    Insert records, or update them if they already exist.

    The SQL is built from FIELDS / KEY_FIELDS / UPDATE_FIELDS. Named
    placeholders (:company, ...) let sqlite read values straight from
    each record dict, and executemany sends all rows in one call.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

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

def print_report(records):
    """Print the number of partners and each name with its website."""
    print()
    print("=" * 45)
    print("PIG GENETICS DISCOVERY REPORT")
    print("=" * 45)
    print("Companies:", len(records))
    print("With websites:", sum(bool(r["website"]) for r in records))

    print()
    print("Discovered companies:")

    for record in records:
        print(f"  {record['company']} | {record['website']}")

    print("=" * 45)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 18: PIG GENETICS DISCOVERY")
    print("=" * 45)

    records = extract_companies(download_directory())

    if not records:
        raise RuntimeError("No pig genetics partners extracted.")

    save_csv(records)
    save_database(records)
    print_report(records)


if __name__ == "__main__":
    main()
