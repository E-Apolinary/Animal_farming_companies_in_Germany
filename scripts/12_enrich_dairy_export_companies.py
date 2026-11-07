import re
import sqlite3
import time

from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


# -----------------------------------
# CONFIGURATION
# -----------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT / "data/database/animal_farming_germany_v2.db"
)

EXPORT_SOURCE = "Export-Union Dairy Member Directory"

MIV_SOURCE = (
    "MIV Milchindustrie-Verband Member Directory"
)

REQUEST_DELAY = 0.5


# -----------------------------------
# DATABASE
# -----------------------------------

def get_candidates(conn):

    return conn.execute(
        """
        SELECT DISTINCT
            e.company,
            e.source_url
        FROM discovery_candidates e
        WHERE e.source_name = ?
          AND e.source_url LIKE
              'https://www.export-union.de/%'
          AND NOT EXISTS (
              SELECT 1
              FROM discovery_candidates m
              WHERE m.source_name = ?
                AND LOWER(TRIM(m.company)) =
                    LOWER(TRIM(e.company))
          )
          AND (
              COALESCE(TRIM(e.website), '') = ''
              OR COALESCE(TRIM(e.email), '') = ''
              OR COALESCE(TRIM(e.phone), '') = ''
          )
        ORDER BY e.company, e.source_url
        """,
        (EXPORT_SOURCE, MIV_SOURCE)
    ).fetchall()


# -----------------------------------
# PARSE COMPANY PROFILE
# -----------------------------------

def extract_profile(session, url):

    response = session.get(
        url,
        timeout=40
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    website = ""
    email = ""
    phone = ""

    # Official company website
    website_link = soup.select_one(
        ".web-info a[href^='http']"
    )

    if website_link:

        candidate = website_link.get(
            "href",
            ""
        ).strip()

        parsed = urlparse(candidate)

        if parsed.scheme in ("http", "https"):
            website = candidate

    # Email
    email_link = soup.select_one(
        ".web-info a[href^='mailto:']"
    )

    if email_link:

        email = email_link.get(
            "href",
            ""
        ).replace(
            "mailto:",
            "",
            1
        ).split("?")[0].strip()

    # Phone
    phone_element = soup.select_one(
        ".phone-info"
    )

    if phone_element:

        phone = phone_element.get_text(
            " ",
            strip=True
        )

    return {
        "website": website,
        "email": email,
        "phone": phone
    }


# -----------------------------------
# UPDATE EXISTING RECORDS
# -----------------------------------

def update_company(conn, company, source_url, details):

    cursor = conn.execute(
        """
        UPDATE discovery_candidates
        SET
            website = CASE
                WHEN TRIM(COALESCE(website, '')) = ''
                THEN ?
                ELSE website
            END,

            email = CASE
                WHEN TRIM(COALESCE(email, '')) = ''
                THEN ?
                ELSE email
            END,

            phone = CASE
                WHEN TRIM(COALESCE(phone, '')) = ''
                THEN ?
                ELSE phone
            END

        WHERE source_name = ?
          AND company = ?
          AND source_url = ?
        """,
        (
            details["website"],
            details["email"],
            details["phone"],
            EXPORT_SOURCE,
            company,
            source_url
        )
    )

    return cursor.rowcount


# -----------------------------------
# MAIN
# -----------------------------------

def main():

    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 12: DAIRY COMPANY ENRICHMENT")
    print("=" * 45)

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 "
            "(compatible; AnimalFarmingGermanyResearch/1.0)"
        )
    })

    processed = 0
    websites_found = 0
    emails_found = 0
    phones_found = 0
    failed = 0

    with sqlite3.connect(DB_PATH) as conn:

        candidates = get_candidates(conn)

        print(
            "Company profiles to inspect:",
            len(candidates)
        )

        for index, (company, url) in enumerate(
            candidates,
            start=1
        ):

            print(
                f"[{index}/{len(candidates)}] "
                f"{company}"
            )

            try:

                details = extract_profile(
                    session,
                    url
                )

                if not any(details.values()):
                    print("  No contact details found.")
                    continue

                update_company(
                    conn,
                    company,
                    url,
                    details
                )

                conn.commit()

                processed += 1

                websites_found += bool(
                    details["website"]
                )

                emails_found += bool(
                    details["email"]
                )

                phones_found += bool(
                    details["phone"]
                )

                print(
                    "  Website:",
                    details["website"] or "-"
                )

            except requests.RequestException as error:

                failed += 1

                print(
                    "  Request failed:",
                    error
                )

            time.sleep(REQUEST_DELAY)

    print()
    print("=" * 45)
    print("DAIRY ENRICHMENT REPORT")
    print("=" * 45)

    print("Profiles enriched:", processed)
    print("Websites found:", websites_found)
    print("Emails found:", emails_found)
    print("Phones found:", phones_found)
    print("Request failures:", failed)

    print("=" * 45)
    print("Database updated successfully.")


if __name__ == "__main__":
    main()