import csv
import re
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


# -----------------------------------
# CONFIGURATION
# -----------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
CSV_PATH = ROOT / "data/raw/brs_companies.csv"

SOURCE_URL = "https://www.rind-schwein.de/mitglieder/de/list/"
SOURCE_NAME = "BRS Member Directory"

# Provisional classification: the BRS directory
# also contains associations and other businesses.
SECTOR = "Cattle and Pig Value Chain - Subsector Unverified"

CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

FIELDS = [
    "company",
    "sector",
    "city",
    "postal_code",
    "address",
    "website",
    "email",
    "phone",
    "description",
    "source_name",
    "source_url",
    "collected_at",
]


# -----------------------------------
# EXTRACT DIRECTORY
# -----------------------------------

def collect_companies():

    companies = []
    seen = set()

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        try:

            page = browser.new_page()

            print("Opening BRS directory...")

            page.goto(
                SOURCE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            table = page.locator(
                "#fancylist_memberlist_table"
            )

            table.wait_for(timeout=30000)

            # Display every member on one page.
            page.locator(
                'select[name="lines"]'
            ).select_option("500")

            # Wait for the complete table to load.
            page.wait_for_function(
                """() => {
                    const rows = document.querySelectorAll(
                        '#fancylist_memberlist_table tr'
                    );
                    return rows.length > 150;
                }""",
                timeout=30000,
            )

            rows = page.locator(
                "#fancylist_memberlist_table tr"
            )

            print("Table rows:", rows.count())

            for i in range(rows.count()):

                row = rows.nth(i)

                cells = row.locator("td")

                # Skip header rows.
                if cells.count() < 4:
                    continue

                name_link = cells.nth(0).locator("a")

                if name_link.count() == 0:
                    continue

                company = name_link.first.inner_text().strip()

                postal_code = cells.nth(1).inner_text().strip()
                city = cells.nth(2).inner_text().strip()

                contact_cell = cells.nth(3)

                website = ""
                email = ""

                links = contact_cell.locator("a")

                for j in range(links.count()):

                    href = (
                        links.nth(j).get_attribute("href") or ""
                    ).strip()

                    if href.startswith("mailto:"):
                        email = href[7:]

                    elif href.startswith(("http://", "https://")):
                        website = href

                detail_href = (
                    name_link.first.get_attribute("href") or ""
                )

                detail_url = urljoin(
                    SOURCE_URL,
                    detail_href
                )

                if not company:
                    continue

                # This source exposes postal code and city,
                # but not the full street address.
                partial_address = " ".join(
                    part
                    for part in [postal_code, city]
                    if part
                )

                key = (
                    company.casefold(),
                    postal_code,
                    city.casefold(),
                )

                if key in seen:
                    continue

                seen.add(key)

                companies.append({
                    "company": company,
                    "sector": SECTOR,
                    "city": city,
                    "postal_code": postal_code,
                    "address": partial_address,
                    "website": website,
                    "email": email,
                    "phone": "",
                    "description": "",
                    "source_name": SOURCE_NAME,
                    "source_url": detail_url,
                    "collected_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                })

        finally:
            browser.close()

    return companies


# -----------------------------------
# SAVE CSV
# -----------------------------------

def save_csv(companies):

    with CSV_PATH.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS
        )

        writer.writeheader()
        writer.writerows(companies)

    print("CSV saved:", CSV_PATH)


# -----------------------------------
# SAVE SQLITE
# -----------------------------------

def save_database(companies):

    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:

        exists = conn.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'discovery_candidates'
        """).fetchone()

        if not exists:
            raise RuntimeError(
                "discovery_candidates table not found."
            )

        for record in companies:

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
                    city = excluded.city,
                    postal_code = excluded.postal_code,
                    website = excluded.website,
                    email = excluded.email,
                    source_url = excluded.source_url,
                    collected_at = excluded.collected_at

            """, tuple(
                record[field]
                for field in FIELDS
            ))

    print("Database updated:", DB_PATH)


# -----------------------------------
# MAIN
# -----------------------------------

def main():

    print("=" * 45)
    print("STEP 8: BRS INDUSTRY DISCOVERY")
    print("=" * 45)

    companies = collect_companies()

    print("Member records collected:", len(companies))

    # Validate completeness before inserting data.
    if not 170 <= len(companies) <= 250:

        raise RuntimeError(
            "Unexpected number of BRS records. "
            "Review the directory before importing."
        )

    save_csv(companies)
    save_database(companies)

    print("\nCollection completed successfully.")


if __name__ == "__main__":
    main()