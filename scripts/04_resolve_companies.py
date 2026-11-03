import hashlib #this module provides a way to securely hash data using various algorithms, including SHA-256, which is used in this script to generate unique company IDs based on normalized company names.
import re #this module provides support for regular expressions, which are used in this script for pattern matching and text manipulation, such as normalizing company names and extracting postal codes from addresses.
import sqlite3
import unicodedata #this module provides access to the Unicode Character Database, which is used in this script to normalize company names by converting them to a standard form, removing diacritics, and ensuring consistent representation of characters.

from pathlib import Path #this module provides classes for manipulating filesystem paths in a platform-independent way, which is used in this script to construct the path to the SQLite database file.
from urllib.parse import urlparse


# ---------------------------------------
# CONFIGURATION
# ---------------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = (
    ROOT
    / "data"
    / "database"
    / "animal_farming_germany_v2.db"
)


# ---------------------------------------
# NORMALIZE COMPANY NAMES
# ---------------------------------------

def normalize_name(name):

    if not name:
        return ""

    name = unicodedata.normalize(
        "NFKC",
        str(name)
    ) #NFKC normalization converts characters to their canonical form, ensuring that visually similar characters are treated as equivalent. This helps in standardizing company names for comparison and matching.

    name = name.casefold().strip()

    name = re.sub(
        r"[^\w\s]",
        " ",
        name
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name.strip()


# ---------------------------------------
# GENERATE STABLE COMPANY IDs
# ---------------------------------------

def generate_company_id(normalized_name):

    digest = hashlib.sha256(
        normalized_name.encode("utf-8")
    ).hexdigest()

    return "COMP_" + digest[:20]


# ---------------------------------------
# EXTRACT WEBSITE DOMAIN
# ---------------------------------------

def extract_domain(website):

    if not website:
        return None

    website = website.strip()

    if not website.startswith(
        ("http://", "https://")
    ):
        website = "https://" + website

    hostname = urlparse(website).hostname

    if not hostname:
        return None

    return hostname.lower().removeprefix("www.")


# ---------------------------------------
# CREATE RESOLUTION TABLES
# ---------------------------------------

def create_tables(conn):

    conn.execute("""
        CREATE TABLE IF NOT EXISTS
        resolved_companies (

            company_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            website TEXT,
            city TEXT

        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS
        resolved_company_sectors (

            company_id TEXT NOT NULL,
            sector TEXT NOT NULL,

            PRIMARY KEY (
                company_id,
                sector
            ),

            FOREIGN KEY (company_id)
                REFERENCES resolved_companies(company_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS
        resolved_company_sources (

            company_id TEXT NOT NULL,
            discovery_id INTEGER NOT NULL UNIQUE,
            source_name TEXT NOT NULL,

            PRIMARY KEY (
                company_id,
                discovery_id
            ),

            FOREIGN KEY (company_id)
                REFERENCES resolved_companies(company_id)
        )
    """)


# ---------------------------------------
# RESOLVE COMPANIES
# ---------------------------------------

def resolve_companies(conn):

    conn.row_factory = sqlite3.Row

    records = conn.execute("""
        SELECT
            id,
            company,
            sector,
            city,
            website,
            source_name
        FROM discovery_candidates
        ORDER BY id
    """).fetchall()

    if not records:
        raise RuntimeError(
            "No discovery candidates found."
        )

    processed = 0
    skipped = 0

    for record in records:

        company = record["company"]
        sector = record["sector"]
        website = record["website"]
        city = record["city"]

        normalized = normalize_name(company)

        if not normalized:
            skipped += 1
            continue

        company_id = generate_company_id(
            normalized
        )

        # Create or update canonical company.
        # Existing non-empty values are preserved.

        conn.execute("""
            INSERT INTO resolved_companies (
                company_id,
                company_name,
                normalized_name,
                website,
                city
            )

            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(company_id)
            DO UPDATE SET

                website = CASE
                    WHEN resolved_companies.website IS NULL
                      OR TRIM(resolved_companies.website) = ''
                    THEN excluded.website
                    ELSE resolved_companies.website
                END,

                city = CASE
                    WHEN resolved_companies.city IS NULL
                      OR TRIM(resolved_companies.city) = ''
                    THEN excluded.city
                    ELSE resolved_companies.city
                END

        """, (
            company_id,
            company,
            normalized,
            website,
            city
        ))

        # A company can operate in multiple sectors.

        if sector:

            conn.execute("""
                INSERT OR IGNORE INTO
                resolved_company_sectors (
                    company_id,
                    sector
                )

                VALUES (?, ?)
            """, (
                company_id,
                sector
            ))

        # Preserve original source record.

        conn.execute("""
            INSERT INTO resolved_company_sources (
                company_id,
                discovery_id,
                source_name
            )

            VALUES (?, ?, ?)

            ON CONFLICT(discovery_id)
            DO UPDATE SET
                company_id = excluded.company_id,
                source_name = excluded.source_name

        """, (
            company_id,
            record["id"],
            record["source_name"]
        ))

        processed += 1

    return processed, skipped


# ---------------------------------------
# IDENTIFY SHARED WEBSITE DOMAINS
# ---------------------------------------

def report_shared_domains(conn):

    companies = conn.execute("""
        SELECT
            company_id,
            company_name,
            website
        FROM resolved_companies
    """).fetchall()

    domains = {}

    for company in companies:

        domain = extract_domain(
            company["website"]
        )

        if not domain:
            continue

        domains.setdefault(
            domain,
            []
        ).append(company)

    shared = {
        domain: records
        for domain, records in domains.items()
        if len(records) > 1
    }

    print("\nPotentially related companies:")

    if not shared:
        print("No shared domains detected.")

    for domain, records in shared.items():

        print(f"\nDomain: {domain}")

        for record in records:
            print(
                " -",
                record["company_name"]
            )


# ---------------------------------------
# DATABASE SUMMARY
# ---------------------------------------

def print_summary(conn):

    companies = conn.execute("""
        SELECT COUNT(*)
        FROM resolved_companies
    """).fetchone()[0]

    sectors = conn.execute("""
        SELECT COUNT(DISTINCT sector)
        FROM resolved_company_sectors
    """).fetchone()[0]

    relationships = conn.execute("""
        SELECT COUNT(*)
        FROM resolved_company_sectors
    """).fetchone()[0]

    sources = conn.execute("""
        SELECT COUNT(*)
        FROM resolved_company_sources
    """).fetchone()[0]

    print("\nDATABASE SUMMARY")
    print("---------------------------")
    print("Resolved companies:", companies)
    print("Industry sectors:", sectors)
    print("Company-sector links:", relationships)
    print("Linked source records:", sources)


# ---------------------------------------
# MAIN
# ---------------------------------------

def main():

    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}"
        )

    print("Starting company resolution...")

    with sqlite3.connect(DB_PATH) as conn:

        conn.execute("PRAGMA foreign_keys = ON")

        create_tables(conn)

        processed, skipped = resolve_companies(conn)

        print("Records processed:", processed)
        print("Records skipped:", skipped)

        print_summary(conn)

        report_shared_domains(conn)

    print("\nCompany resolution completed.")


if __name__ == "__main__":
    main()