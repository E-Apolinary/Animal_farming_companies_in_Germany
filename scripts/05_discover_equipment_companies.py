# -----------------------------------
# HANDLE COOKIE CONSENT
# -----------------------------------

def handle_cookie_consent(page):

    """
    Accept only necessary cookies if the
    website displays a consent dialog.
    """

    from playwright.sync_api import TimeoutError

    cookie_buttons = [
        "Nur notwendige Cookies",
        "Nur notwendige",
        "Alle ablehnen",
        "Ablehnen",
        "Reject All",
        "Deny All",
    ]

    for button_text in cookie_buttons:

        try:

            button = page.get_by_role(
                "button",
                name=button_text,
                exact=True
            )

            if button.count() > 0:

                button.first.click(timeout=3000)

                print(
                    "Cookie dialog handled:",
                    button_text
                )

                return True

        except TimeoutError:
            continue

    return False

import csv
import re
import sqlite3

from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# -----------------------------------
# CONFIGURATION
# -----------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
CSV_PATH = ROOT / "data/raw/vdma_landtechnik_companies.csv"

SOURCE_URL = "https://www.vdma.eu/de/mitglieder-landtechnik"
SOURCE_NAME = "VDMA Landtechnik Member Directory"
SECTOR = "Agricultural Machinery - Relevance Unverified"

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
    "collected_at"
]


# -----------------------------------
# EXTRACT ONE PAGE
# -----------------------------------

def extract_page(page):

    results = []

    cards = page.locator(".association-member")

    for i in range(cards.count()):

        card = cards.nth(i)

        name = card.locator(
            ".association-member__title"
        ).inner_text().strip()

        address_lines = card.locator(
            ".association-member__info-address li"
        ).all_inner_texts()

        address_lines = [
            line.strip()
            for line in address_lines
            if line.strip()
        ]

        # Keep only German company locations.
        if not address_lines:
            continue

        if address_lines[-1].casefold() != "deutschland":
            continue

        address = " | ".join(address_lines[:-1])

        city = ""
        postal_code = ""

        for line in address_lines:

            match = re.match(
                r"^(\d{5})\s+(.+)$",
                line
            )

            if match:
                postal_code = match.group(1)
                city = match.group(2).strip()
                break

        website = ""
        email = ""
        phone = ""

        links = card.locator(
            ".association-member__info-contacts a"
        )

        for j in range(links.count()):

            link = links.nth(j)

            href = (
                link.get_attribute("href") or ""
            ).strip()

            if href.startswith("mailto:"):

                email = href[7:]

            elif href.startswith("tel:"):

                phone = href[4:]

            elif href.startswith(("http://", "https://")):

                website = href

        if not name:
            continue

        results.append({
            "company": name,
            "sector": SECTOR,
            "city": city,
            "postal_code": postal_code,
            "address": address,
            "website": website,
            "email": email,
            "phone": phone,
            "description": "",
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "collected_at": datetime.now(
                timezone.utc
            ).isoformat()
        })

    return results


# -----------------------------------
# SAVE CSV CHECKPOINT
# -----------------------------------

def save_csv(records):

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


# -----------------------------------
# GET CURRENT PAGE SIGNATURE
# -----------------------------------

def get_page_signature(page):

    """
    Identify the current page using all visible
    company names, rather than the page indicator.
    """

    names = page.locator(
        ".association-member__title"
    ).all_inner_texts()

    return "|".join(
        name.strip()
        for name in names
    )


# -----------------------------------
# COLLECT ALL PAGES
# -----------------------------------

def collect():

    records = []
    seen_companies = set()
    seen_pages = set()

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        try:

            page = browser.new_page()

            print("Opening VDMA directory...")

            page.goto(
                SOURCE_URL,
                wait_until="domcontentloaded",
                timeout=60000
            )
# Handle cookie consent
            handle_cookie_consent(page)
            page.locator(
                ".association-member"
            ).first.wait_for(timeout=30000)

            total_pages = int(
                page.locator(
                    ".vdma-pagination"
                ).get_attribute("data-total-pages")
            )

            print(f"Directory pages: {total_pages}")
            print("-----------------------------------")

            for page_number in range(1, total_pages + 1):

                page.locator(
                    ".association-member"
                ).first.wait_for(timeout=30000)

                # Identify the current company list.
                current_signature = get_page_signature(page)

                if current_signature in seen_pages:

                    raise RuntimeError(
                        f"Repeated company list detected "
                        f"on page {page_number}. "
                        f"Checkpoint saved at {CSV_PATH}."
                    )

                seen_pages.add(current_signature)

                # Extract companies from the current page.
                extracted = extract_page(page)

                for record in extracted:

                    key = (
                        record["company"].casefold(),
                        record["address"].casefold()
                    )

                    if key not in seen_companies:

                        seen_companies.add(key)

                        records.append(record)

                # Save progress after every page.
                save_csv(records)

                print(
                    f"Page {page_number}/{total_pages}: "
                    f"{len(extracted)} German entries | "
                    f"{len(records)} unique candidates"
                )

                # Stop after the last page.
                if page_number == total_pages:
                    break

                # -----------------------------------
                # PAGINATION FIX
                # -----------------------------------

                # Remember the current list BEFORE clicking.
                previous_signature = current_signature

                # Click Next exactly once.
# Check whether the cookie dialog appeared.
                handle_cookie_consent(page)

                page.locator(
                    ".vdma-pagination-right"
                ).click(timeout=15000)

                # Wait for the company list to change.
                try:

                    page.wait_for_function(
                        """previous => {
                            const names = Array.from(
                                document.querySelectorAll(
                                    '.association-member__title'
                                )
                            ).map(
                                element => element.textContent.trim()
                            );

                            return names.length > 0 &&
                                   names.join('|') !== previous;
                        }""",
                        arg=previous_signature,
                        timeout=30000
                    )

                except PlaywrightTimeout:

                    raise RuntimeError(
                        f"Pagination failed after page "
                        f"{page_number}. "
                        f"Checkpoint saved at {CSV_PATH}. "
                        "Database has not been updated."
                    )

        finally:

            browser.close()

    return records


# -----------------------------------
# SAVE TO SQLITE
# -----------------------------------

def save_database(records):

    if not DB_PATH.is_file():

        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    with sqlite3.connect(DB_PATH) as conn:

        # Confirm that our discovery table exists.
        table_exists = conn.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
            AND name = 'discovery_candidates'
        """).fetchone()

        if not table_exists:

            raise RuntimeError(
                "Table 'discovery_candidates' "
                "does not exist."
            )

        for record in records:

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
                    phone = excluded.phone,
                    source_url = excluded.source_url,
                    collected_at = excluded.collected_at

            """, tuple(
                record[field]
                for field in FIELDS
            ))

    print("Database updated successfully.")


# -----------------------------------
# DATA QUALITY REPORT
# -----------------------------------

def quality_report(records):

    total = len(records)

    with_websites = sum(
        bool(record["website"])
        for record in records
    )

    with_cities = sum(
        bool(record["city"])
        for record in records
    )

    missing_websites = total - with_websites
    missing_cities = total - with_cities

    print("\n" + "=" * 45)
    print("VDMA DATA COLLECTION REPORT")
    print("=" * 45)

    print(f"Total German candidates: {total}")
    print(f"Companies with websites: {with_websites}")
    print(f"Companies without websites: {missing_websites}")
    print(f"Companies with cities: {with_cities}")
    print(f"Companies without cities: {missing_cities}")

    if total > 0:

        coverage = with_websites / total * 100

        print(
            f"Website coverage: {coverage:.1f}%"
        )

    print("=" * 45)


# -----------------------------------
# MAIN
# -----------------------------------

def main():

    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 5: VDMA COMPANY DISCOVERY")
    print("=" * 45)

    # Collect every directory page.
    records = collect()

    if not records:

        raise RuntimeError(
            "No German companies extracted."
        )

    print("\nAll directory pages processed.")

    # Display data-quality statistics.
    quality_report(records)

    # Update SQLite only after complete collection.
    save_database(records)

    print("\nFiles:")
    print("CSV:", CSV_PATH)
    print("Database:", DB_PATH)

    print("\nStep 5 completed successfully.")


if __name__ == "__main__":
    main()