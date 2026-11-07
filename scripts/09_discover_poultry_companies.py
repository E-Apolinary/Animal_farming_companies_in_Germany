import csv
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
CSV_PATH = ROOT / "data/raw/ngw_poultry_companies.csv"

SOURCE_URL = "https://www.ngw-landesverband.de/mitglieder"
SOURCE_NAME = "NGW Poultry Member Directory"

SECTOR = "Poultry Value Chain - Subsector Unverified"

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
# DOWNLOAD DIRECTORY
# -----------------------------------

def download_directory():

    session = requests.Session()

    try:

        for attempt in range(1, 4):

            try:

                response = session.get(
                    SOURCE_URL,
                    timeout=30,
                    headers={
                        "User-Agent": (
                            "AnimalFarmingGermanyResearch/1.0"
                        )
                    },
                )

                response.raise_for_status()

                return BeautifulSoup(
                    response.content,
                    "html.parser",
                )

            except requests.RequestException as error:

                print(
                    f"Attempt {attempt} failed: {error}"
                )

                if attempt == 3:
                    raise

                time.sleep(attempt * 3)

    finally:
        session.close()


# -----------------------------------
# EXTRACT COMPANY PROFILES
# -----------------------------------

def extract_companies(soup):

    companies = []

    cards = soup.select(".t_entry")

    print("Profile cards found:", len(cards))

    def field(card, css_selector):

        element = card.select_one(css_selector)

        if element is None:
            return ""

        return element.get_text(" ", strip=True)

    seen = set()

    for card in cards:

        company = field(
            card,
            ".t_entry_name_1"
        )

        street = field(
            card,
            ".t_entry_street"
        )

        postal_code = field(
            card,
            ".t_entry_postal_code"
        )

        city = field(
            card,
            ".t_entry_city"
        )

        phone = field(
            card,
            ".t_entry_phone"
        )

        description = field(
            card,
            ".t_entry_observations"
        )

        website = ""

        website_link = card.select_one(
            ".t_entry_www a[href]"
        )

        if website_link:

            website = urljoin(
                SOURCE_URL,
                website_link["href"].strip()
            )

        # The website protects some email addresses
        # using obfuscation. Leave them blank rather
        # than extracting incorrect values.
        email = ""

        address = " | ".join(
            part
            for part in [
                street,
                f"{postal_code} {city}".strip()
            ]
            if part
        )

        if not company:
            continue

        key = (
            company.casefold(),
            address.casefold()
        )

        if key in seen:
            continue

        seen.add(key)

        companies.append({
            "company": company,
            "sector": SECTOR,
            "city": city,
            "postal_code": postal_code,
            "address": address,
            "website": website,
            "email": email,
            "phone": phone,
            "description": description,
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "collected_at": datetime.now(
                timezone.utc
            ).isoformat(),
        })

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
                    phone = excluded.phone,
                    description = excluded.description,
                    source_url = excluded.source_url,
                    collected_at = excluded.collected_at

            """, tuple(
                record[field]
                for field in FIELDS
            ))

    print("Database updated:", DB_PATH)


# -----------------------------------
# QUALITY REPORT
# -----------------------------------

def quality_report(companies):

    total = len(companies)

    websites = sum(
        bool(company["website"])
        for company in companies
    )

    cities = sum(
        bool(company["city"])
        for company in companies
    )

    descriptions = sum(
        bool(company["description"])
        for company in companies
    )

    print("\nNGW DATA QUALITY REPORT")
    print("-" * 35)

    print("Companies:", total)
    print("With websites:", websites)
    print("With cities:", cities)
    print("With descriptions:", descriptions)

    if total:
        print(
            f"Website coverage: "
            f"{websites / total:.1%}"
        )


# -----------------------------------
# MAIN
# -----------------------------------

def main():

    print("=" * 45)
    print("STEP 9: POULTRY COMPANY DISCOVERY")
    print("=" * 45)

    soup = download_directory()

    companies = extract_companies(soup)

    # Detect unexpected extraction failures.
    if not 5 <= len(companies) <= 100:

        raise RuntimeError(
            "Unexpected profile count. "
            "Review the directory structure."
        )

    quality_report(companies)

    save_csv(companies)
    save_database(companies)

    print("\nStep 9 completed successfully.")


if __name__ == "__main__":
    main()