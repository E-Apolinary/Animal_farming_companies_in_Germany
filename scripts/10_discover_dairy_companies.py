import csv
import re
import sqlite3

from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# -----------------------------------
# CONFIGURATION
# -----------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT
    / "data/database/animal_farming_germany_v2.db"
)

CSV_PATH = (
    ROOT
    / "data/raw/miv_dairy_companies.csv"
)

SOURCE_URL = (
    "https://milchindustrie.de/"
    "ueber-uns/unsere-mitglieder/"
)

SOURCE_NAME = (
    "MIV Milchindustrie-Verband Member Directory"
)

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
# HELPER FUNCTIONS
# -----------------------------------

def get_text(card, selector):

    element = card.select_one(selector)

    if element:
        return element.get_text(
            " ",
            strip=True
        )

    return ""


def determine_sector(member_type):

    if member_type == "Firmensitz Förderer":

        return "Dairy Technology and Services"

    return "Dairy Processing and Manufacturing"


# -----------------------------------
# COLLECT DAIRY COMPANIES
# -----------------------------------

def collect():

    print("Opening MIV dairy directory...")

    response = requests.get(
        SOURCE_URL,
        headers={
            "User-Agent": (
                "AnimalFarmingGermanyResearch/1.0"
            )
        },
        timeout=60
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    cards = soup.select(
        "ul.table > li.main-li"
    )

    print(
        "Directory entries found:",
        len(cards)
    )

    if not cards:

        raise RuntimeError(
            "No company cards found. "
            "Website structure may have changed."
        )

    records = []
    seen = set()

    for card in cards:

        company = get_text(
            card,
            ".company-name"
        )

        location = get_text(
            card,
            ".place-postcode"
        )

        member_type = card.get(
            "data-type",
            ""
        )

        if not company:
            continue

        # Exclude association office.
        if member_type == "Geschäftsstelle":
            continue

        # Only keep German locations.
        match = re.match(
            r"^(\d{5})\s+(.+)$",
            location
        )

        if not match:
            continue

        postal_code = match.group(1)

        city = match.group(2).strip()

        street = get_text(
            card,
            ".street"
        )

        address = ", ".join(
            part
            for part in [
                street,
                location
            ]
            if part
        )

        # -----------------------------------
        # WEBSITE
        # -----------------------------------

        website_link = card.select_one(
            ".homepage a[href]"
        )

        website = ""

        if website_link:

            website = (
                website_link.get(
                    "href",
                    ""
                ).strip()
            )

        # -----------------------------------
        # CONTACT DETAILS
        # -----------------------------------

        email = get_text(
            card,
            ".email"
        )

        phone = get_text(
            card,
            ".phone"
        )

        # -----------------------------------
        # PRODUCTS
        # -----------------------------------

        product_elements = card.select(
            ".categories"
        )

        products = ""

        if product_elements:

            products = (
                product_elements[-1]
                .get_text(
                    " ",
                    strip=True
                )
            )

        # -----------------------------------
        # SECTOR
        # -----------------------------------

        sector = determine_sector(
            member_type
        )

        description = (
            f"Directory type: {member_type}. "
            f"Products: {products}"
        )

        # -----------------------------------
        # DUPLICATE CHECK
        # -----------------------------------

        key = (
            company.casefold(),
            address.casefold()
        )

        if key in seen:
            continue

        seen.add(key)

        # -----------------------------------
        # STORE RECORD
        # -----------------------------------

        records.append({

            "company": company,

            "sector": sector,

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
            ).isoformat()

        })

    return records


# -----------------------------------
# SAVE RAW CSV
# -----------------------------------

def save_csv(records):

    CSV_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

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

        writer.writerows(records)

    print(
        "CSV saved:",
        CSV_PATH
    )


# -----------------------------------
# SAVE TO EXISTING DATABASE
# -----------------------------------

def save_database(records):

    if not DB_PATH.is_file():

        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    with sqlite3.connect(DB_PATH) as conn:

        conn.executemany(
            """
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

            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )

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

                phone = excluded.phone,

                description = excluded.description,

                source_url = excluded.source_url,

                collected_at = excluded.collected_at

            """,

            [
                tuple(
                    record[field]
                    for field in FIELDS
                )

                for record in records
            ]
        )

    print(
        "Database updated successfully."
    )


# -----------------------------------
# DATA QUALITY REPORT
# -----------------------------------

def report(records):

    total = len(records)

    with_websites = sum(
        bool(record["website"])
        for record in records
    )

    with_cities = sum(
        bool(record["city"])
        for record in records
    )

    unique_companies = len({
        record["company"].casefold()
        for record in records
    })

    unique_company_locations = len({
        (
            record["company"].casefold(),
            record["address"].casefold()
        )
        for record in records
    })

    print()
    print("=" * 45)
    print("DAIRY DATA COLLECTION REPORT")
    print("=" * 45)

    print(
        "Total German listings:",
        total
    )

    print(
        "Unique company names:",
        unique_companies
    )

    print(
        "Unique company/location pairs:",
        unique_company_locations
    )

    print(
        "Companies with websites:",
        with_websites
    )

    print(
        "Companies with cities:",
        with_cities
    )

    print(
        "Duplicate name/location records:",
        total - unique_company_locations
    )

    if total:

        print(
            "Website coverage:",
            f"{with_websites / total:.1%}"
        )

    print("=" * 45)


# -----------------------------------
# MAIN
# -----------------------------------

def main():

    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 10: DAIRY COMPANY DISCOVERY")
    print("=" * 45)

    records = collect()

    if not records:

        raise RuntimeError(
            "No German dairy companies extracted."
        )

    # Save original discovery records.
    save_csv(records)

    # Insert into existing SQLite database.
    save_database(records)

    # Display collection statistics.
    report(records)

    print()
    print("Dairy company discovery completed.")


if __name__ == "__main__":
    main()