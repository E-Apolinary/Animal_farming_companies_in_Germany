import csv
import re
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString


# -----------------------------------
# CONFIGURATION
# -----------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data/database/animal_farming_germany_v2.db"
)

CSV_PATH = (
    ROOT / "data/raw/dairy_export_union_companies.csv"
)

SOURCE_URL = (
    "https://www.export-union.de/de/"
    "milchexporte/exportmolkereien"
)

SOURCE_NAME = "Export-Union Dairy Member Directory"

SECTOR = "Dairy Value Chain - Subsector Unverified"

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
# HELPERS
# -----------------------------------

def clean(value):
    return " ".join(str(value).split())


def get_text(card, selector):
    element = card.select_one(selector)

    if element:
        return clean(element.get_text(" ", strip=True))

    return ""


# -----------------------------------
# EXTRACT ONE DIRECTORY ENTRY
# -----------------------------------

def extract_record(card):

    company = get_text(card, ".standort-titel")

    if not company:
        return None

    # The operating-site type is stored as a CSS class.
    location_type = ""

    type_element = card.select_one(".standortart")

    if type_element:
        classes = type_element.get("class", [])

        location_type = " ".join(
            cls for cls in classes
            if cls != "standortart"
        )

    # Extract direct text nodes containing the address.
    address_parts = [
        clean(node)
        for node in card.contents
        if isinstance(node, NavigableString)
        and clean(node)
    ]

    location_text = clean(" ".join(address_parts))

    # German postal code + city.
    match = re.search(
        r"(?<!\d)(\d{5})\s+(.+)$",
        location_text
    )

    if not match:
        return None

    postal_code = match.group(1)
    city = clean(match.group(2))

    street = clean(location_text[:match.start()])

    address = ", ".join(
        part for part in [
            street,
            f"{postal_code} {city}"
        ]
        if part
    )

    # Link to the individual Export-Union company profile.
    profile_link = card.select_one("a.more[href]")

    profile_url = SOURCE_URL

    if profile_link:
        profile_url = urljoin(
            SOURCE_URL,
            profile_link.get("href", "")
        )

    description = (
        f"Export-Union directory location type: "
        f"{location_type or 'Not specified'}"
    )

    return {
        "company": company,
        "sector": SECTOR,
        "city": city,
        "postal_code": postal_code,
        "address": address,
        "website": "",
        "email": "",
        "phone": "",
        "description": description,
        "source_name": SOURCE_NAME,
        "source_url": profile_url,
        "collected_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


# -----------------------------------
# COLLECT COMPANIES
# -----------------------------------

def collect():

    print("Opening Export-Union directory...")

    response = requests.get(
        SOURCE_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; AnimalFarmingGermanyResearch/1.0)"
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
        ".standort-titel-betriebsart-wrapper"
    )

    print("Directory entries found:", len(cards))

    if not cards:
        raise RuntimeError(
            "No company cards found. "
            "The directory structure may have changed."
        )

    records = []
    seen = set()

    for card in cards:

        record = extract_record(card)

        if record is None:
            continue

        key = (
            record["company"].casefold(),
            record["address"].casefold()
        )

        if key in seen:
            continue

        seen.add(key)
        records.append(record)

    return records


# -----------------------------------
# SAVE CSV
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

    print("CSV saved:", CSV_PATH)


# -----------------------------------
# SAVE DATABASE
# -----------------------------------

def save_database(records):

    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:

        conn.executemany(
            """
            INSERT INTO discovery_candidates (
                company, sector, city, postal_code,
                address, website, email, phone,
                description, source_name, source_url,
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
                phone = excluded.phone,
                description = excluded.description,
                source_url = excluded.source_url,
                collected_at = excluded.collected_at
            """,
            [
                tuple(record[field] for field in FIELDS)
                for record in records
            ]
        )

    print("Database updated successfully.")


# -----------------------------------
# REPORT
# -----------------------------------

def report(records):

    print()
    print("=" * 45)
    print("DAIRY EXPORT DIRECTORY REPORT")
    print("=" * 45)

    print("Location records:", len(records))

    print(
        "Unique company names:",
        len({
            r["company"].casefold()
            for r in records
        })
    )

    print(
        "Companies with cities:",
        sum(bool(r["city"]) for r in records)
    )

    print(
        "Company profile links:",
        sum(
            r["source_url"] != SOURCE_URL
            for r in records
        )
    )

    print("=" * 45)


# -----------------------------------
# MAIN
# -----------------------------------

def main():

    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 11: DAIRY EXPORT COMPANY DISCOVERY")
    print("=" * 45)

    records = collect()

    if not records:
        raise RuntimeError(
            "No German dairy companies extracted."
        )

    save_csv(records)
    save_database(records)
    report(records)

    print("\nDiscovery completed.")


if __name__ == "__main__":
    main()