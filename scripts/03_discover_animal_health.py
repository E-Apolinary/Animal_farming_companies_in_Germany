import csv
import sqlite3
import time

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup #this module is used for parsing HTML and XML documents, and Tag represents an HTML or XML tag in the parsed document


# ------------------------------------
# CONFIGURATION
# ------------------------------------

ROOT = Path(__file__).resolve().parents[1]

CSV_PATH = ROOT / "data/raw/bft_companies.csv"

DB_PATH = (
    ROOT
    / "data/database/animal_farming_germany_v2.db"
)

SOURCE_URL = (
    "https://www.bft-online.de/"
    "der-verband/mitglieder"
)

SOURCE_NAME = "BfT Member Directory"
SECTOR = "Animal Health & Veterinary Pharmaceuticals"

CSV_PATH.parent.mkdir(parents=True, exist_ok=True)


# ------------------------------------
# DOWNLOAD WEBSITE
# ------------------------------------

def download_directory():

    session = requests.Session()

    for attempt in range(1, 4):

        try:
            response = session.get(
                SOURCE_URL,
                headers={
                    "User-Agent": (
                        "AnimalFarmingGermanyResearch/1.0"
                    )
                },
                timeout=30
            )

            response.raise_for_status()

            return BeautifulSoup(
                response.content,
                "html.parser"
            )

        except requests.RequestException as error:

            print(f"Attempt {attempt} failed: {error}")

            if attempt == 3:
                raise

            time.sleep(attempt * 3)


# ------------------------------------
# EXTRACT COMPANIES
# ------------------------------------

def extract_companies(soup):

    # The current BfT member list is an HTML table.
    # Find the table containing company website links.

    candidate_tables = []

    for table in soup.select("table"): #soup.select("table") finds all <table> elements in the HTML document and returns a list of Tag objects representing those tables.

        links = table.select("td a[href]")

        external_links = [
            link for link in links
            if urlparse(
                urljoin(SOURCE_URL, link.get("href", ""))
            ).hostname not in (
                None,
                "bft-online.de",
                "www.bft-online.de"
            )
        ]

        if len(external_links) >= 15:
            candidate_tables.append(
                (table, external_links)
            )

    if len(candidate_tables) != 1:
        raise RuntimeError(
            "Could not uniquely identify the BfT "
            "member table. Inspect the website structure."
        )

    _, links = candidate_tables[0]

    companies = []

    seen = set()

    for link in links:

        name = link.get_text(" ", strip=True)

        website = urljoin(
            SOURCE_URL,
            link.get("href", "").strip()
        )

        if not name or not website:
            continue

        if name.casefold() in seen:
            continue

        seen.add(name.casefold())

        companies.append({
            "company": name,
            "sector": SECTOR,
            "city": "",
            "postal_code": "",
            "address": "",
            "website": website,
            "email": "",
            "phone": "",
            "description": "",
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "collected_at": datetime.now(
                timezone.utc
            ).isoformat()
        })

    return companies


# ------------------------------------
# SAVE CSV
# ------------------------------------

def save_csv(companies):

    if not companies:
        raise RuntimeError("No BfT companies extracted.")

    with open(
        CSV_PATH,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=list(companies[0].keys())
        )

        writer.writeheader()
        writer.writerows(companies)


# ------------------------------------
# UPDATE EXISTING DATABASE
# ------------------------------------

def save_database(companies):

    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    with sqlite3.connect(DB_PATH) as conn:

        # The DVT script already created this table.
        # Check that it exists before inserting anything.

        exists = conn.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'discovery_candidates'
        """).fetchone()

        if not exists:
            raise RuntimeError(
                "discovery_candidates table is missing."
            )

        for company in companies:

            conn.execute("""
                INSERT INTO discovery_candidates (
                    company,
                    sector,
                    city,
                    postal_code,
                    address,
                    website,
                    email,
                    phone,
                    description,
                    source_name,
                    source_url,
                    collected_at
                )

                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

                ON CONFLICT (
                    source_name,
                    company,
                    address
                )

                DO UPDATE SET
                    sector = excluded.sector,
                    website = excluded.website,
                    source_url = excluded.source_url,
                    collected_at = excluded.collected_at
            """, tuple(company.values()))


# ------------------------------------
# MAIN
# ------------------------------------

def main():

    print("Downloading BfT member directory...")

    soup = download_directory()

    companies = extract_companies(soup)

    print(f"Companies discovered: {len(companies)}")

    # Prevent unexpectedly small or large imports.
    if not 20 <= len(companies) <= 40:
        raise RuntimeError(
            "Unexpected member count. "
            "Review extraction before saving."
        )

    save_csv(companies)

    save_database(companies)

    print("CSV saved:", CSV_PATH)
    print("Database updated:", DB_PATH)


if __name__ == "__main__":
    main()