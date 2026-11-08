"""
STEP 14: Meat processing company discovery.

Scrapes the BVWS (Bundesverband der Wurst- und Schinkenproduzenten)
member directory, visits each member profile, keeps German companies
only, and saves the results to a CSV file and to the
`discovery_candidates` table of the project database.
"""

import csv
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


# -----------------------------------
# CONFIGURATION
# -----------------------------------

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
CSV_PATH = ROOT / "data/raw/bvws_meat_processing_companies.csv"

SOURCE_URL = "https://www.wurstproduzenten.de/verband/alle-mitglieder"
SOURCE_NAME = "BVWS Meat Processing Member Directory"
SECTOR = "Meat Processing and Manufacturing"
DESCRIPTION = "BVWS member company involved in meat product manufacturing."

# Column order for both the CSV file and the database insert.
FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]

# Columns that form the table's unique key (used in ON CONFLICT).
KEY_FIELDS = ("source_name", "company", "address")

# A German location line looks like "12345 City".
# Compiled once instead of on every profile line.
LOCATION_RE = re.compile(r"^(\d{5})\s+(.+)$")

# Profile lines that are neither street nor useful contact data.
IGNORED_PREFIXES = ("Telefax:", "E-Mail:", "Internet:")

# Pause between profile requests to be polite to the server.
REQUEST_DELAY = 0.5


# -----------------------------------
# HELPERS
# -----------------------------------

def clean(value):
    """Collapse all whitespace (spaces, tabs, newlines) to single spaces."""
    return " ".join(str(value).split())


def fetch(session, url):
    """Download a page and return it parsed as HTML."""
    response = session.get(url, timeout=45)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def link_href(element, selector):
    """Return the href of the first link matching selector, or ''."""
    link = element.select_one(selector)
    return link.get("href", "").strip() if link else ""


# -----------------------------------
# EXTRACT COMPANY PROFILE
# -----------------------------------

def extract_profile(session, url, collected_at):
    """
    Parse one member profile page into a record dict.

    Returns None when the page has no company heading or no German
    postal code, so callers can skip it.
    """
    article = fetch(session, url).select_one(".article.unternehmen")
    heading = article.select_one("h1") if article else None

    if heading is None:
        return None

    street = location = phone = email = website = ""

    # Each address / contact detail sits in its own top-level <div>.
    # The line's prefix tells us which field it belongs to.
    for element in article.find_all("div", recursive=False):
        value = clean(element.get_text(" ", strip=True))

        if not value:
            continue
        if LOCATION_RE.match(value):
            location = value
        elif value.startswith("Telefon:"):
            phone = clean(value.removeprefix("Telefon:"))
        elif value.startswith("Kontakt:"):
            # "mailto:info@x.de?subject=..." -> "info@x.de"
            email = (
                link_href(element, "a[href^='mailto:']")
                .removeprefix("mailto:")
                .split("?")[0]
            )
        elif value.startswith("Webseite:"):
            website = link_href(element, "a[href^='http']")
        elif not street and not value.startswith(IGNORED_PREFIXES):
            # The first unlabelled line is the street address.
            street = value

    # No 5-digit postal code means the company is not in Germany.
    match = LOCATION_RE.match(location)

    if not match:
        return None

    return {
        "company": clean(heading.get_text(" ", strip=True)),
        "sector": SECTOR,
        "city": clean(match.group(2)),
        "postal_code": match.group(1),
        "address": ", ".join(part for part in (street, location) if part),
        "website": website,
        "email": email,
        "phone": phone,
        "description": DESCRIPTION,
        "source_name": SOURCE_NAME,
        "source_url": url,
        "collected_at": collected_at,
    }


# -----------------------------------
# COLLECT COMPANIES
# -----------------------------------

def collect():
    """Walk the directory listing and extract every member profile."""
    records = []
    seen = set()  # (company, address) pairs already collected

    # One timestamp for the whole run, so all records share it.
    collected_at = datetime.now(timezone.utc).isoformat()

    # A session reuses the TCP connection across all requests.
    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (compatible; AnimalFarmingGermanyResearch/1.0)"
    )

    print("Opening BVWS member directory...")

    cards = fetch(session, SOURCE_URL).select(".item-wrapper")
    print("Directory entries found:", len(cards))

    if not cards:
        raise RuntimeError("No meat-processing company cards found.")

    for index, card in enumerate(cards, start=1):
        name = card.select_one(".item-titel")
        link = card.select_one("a.more[href]")

        if not name or not link:
            continue

        print(f"[{index}/{len(cards)}] {clean(name.get_text(' ', strip=True))}")

        # Only the network call can raise RequestException, so the
        # try block stays small. `finally` pauses after every request,
        # including failed ones.
        try:
            record = extract_profile(
                session, urljoin(SOURCE_URL, link["href"]), collected_at
            )
        except requests.RequestException as error:
            print("  Request failed:", error)
            continue
        finally:
            time.sleep(REQUEST_DELAY)

        if record is None:
            print("  Skipped: incomplete profile")
            continue

        # Skip duplicates (same company at the same address).
        key = (record["company"].casefold(), record["address"].casefold())

        if key not in seen:
            seen.add(key)
            records.append(record)

    return records


# -----------------------------------
# SAVE
# -----------------------------------

def save_csv(records):
    """Write records to CSV (utf-8-sig so Excel shows umlauts correctly)."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    print("CSV saved:", CSV_PATH)


def save_database(records):
    """
    Insert records, or update them if they already exist.

    The SQL is built from FIELDS, so adding a column only requires
    changing FIELDS. Named placeholders (:company, ...) let sqlite read
    values straight from each record dict.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    columns = ", ".join(FIELDS)
    placeholders = ", ".join(f":{field}" for field in FIELDS)
    updates = ", ".join(
        f"{field} = excluded.{field}"
        for field in FIELDS
        if field not in KEY_FIELDS
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


# -----------------------------------
# REPORT
# -----------------------------------

def report(records):
    """Print a short summary of how complete the collected data is."""

    def count(field):
        return sum(bool(r[field]) for r in records)

    print()
    print("=" * 45)
    print("MEAT PROCESSING DISCOVERY REPORT")
    print("=" * 45)
    print("Records collected:", len(records))
    print("Unique company names:", len({r["company"].casefold() for r in records}))
    print("Companies with websites:", count("website"))
    print("Companies with cities:", count("city"))
    print("Companies with emails:", count("email"))
    print("=" * 45)


# -----------------------------------
# MAIN
# -----------------------------------

def main():
    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 14: MEAT PROCESSING DISCOVERY")
    print("=" * 45)

    records = collect()

    if not records:
        raise RuntimeError("No German meat-processing companies extracted.")

    save_csv(records)
    save_database(records)
    report(records)

    print("\nDiscovery completed.")


if __name__ == "__main__":
    main()
