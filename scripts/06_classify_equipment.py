import csv
import re
import sqlite3
import time

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


# ----------------------------------------
# CONFIGURATION
# ----------------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"

CSV_PATH = ROOT / "data/processed/vdma_classification.csv"

CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

SOURCE_NAME = "VDMA Landtechnik Member Directory"

USER_AGENT = "AnimalFarmingGermanyResearch/1.0"

REQUEST_DELAY = 1.5
TIMEOUT = 15


# ----------------------------------------
# CLASSIFICATION KEYWORDS
# ----------------------------------------

DIRECT_KEYWORDS = [
    "stalltechnik",
    "stalleinrichtung",
    "stallausrüstung",
    "stallbau",
    "melktechnik",
    "melkroboter",
    "melkanlage",
    "milking system",
    "dairy farming",
    "livestock equipment",
    "livestock housing",
    "animal housing",
    "feeding system",
    "fütterungsanlage",
    "fütterungstechnik",
    "automatische fütterung",
    "schweinehaltung",
    "rinderhaltung",
    "geflügelhaltung",
    "tierhaltung",
    "nutztierhaltung",
    "herdenmanagement",
    "entmistung",
    "gülletechnik",
]

INDIRECT_KEYWORDS = [
    "futterernte",
    "futtererntetechnik",
    "futteraufbereitung",
    "futterproduktion",
    "futtermischwagen",
    "silagetechnik",
    "silage",
    "forage harvester",
    "forage equipment",
    "feed production",
    "feed processing",
    "grassland equipment",
    "grünlandtechnik",
    "ballenpresse",
]

CROP_KEYWORDS = [
    "bodenbearbeitung",
    "pflanzenschutztechnik",
    "sätechnik",
    "saattechnik",
    "crop protection",
    "crop farming",
    "seed drilling",
    "soil cultivation",
    "ackerbau",
    "pflanzenbau",
    "mähdrescher",
    "combine harvester",
]


# ----------------------------------------
# DATABASE CONNECTION
# ----------------------------------------

def connect_database():

    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn


# ----------------------------------------
# CREATE CLASSIFICATION TABLE
# ----------------------------------------

def create_table(conn):

    conn.execute("""
        CREATE TABLE IF NOT EXISTS
        company_relevance (

            discovery_id INTEGER PRIMARY KEY,

            company TEXT,

            relevance TEXT,

            matched_keywords TEXT,

            evidence_url TEXT,

            classification_status TEXT,

            checked_at TEXT,

            FOREIGN KEY(discovery_id)
                REFERENCES discovery_candidates(id)
        )
    """)

    conn.commit()


# ----------------------------------------
# CHECK ROBOTS.TXT
# ----------------------------------------

def robots_allowed(session, url):

    parsed = urlparse(url)

    robots_url = (
        f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    )

    try:

        response = session.get(
            robots_url,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT}
        )

        if response.status_code == 404:
            return True

        if response.status_code != 200:
            return False

        parser = RobotFileParser()

        parser.parse(response.text.splitlines())

        return parser.can_fetch(USER_AGENT, url)

    except requests.RequestException:
        return False


# ----------------------------------------
# DOWNLOAD WEBSITE TEXT
# ----------------------------------------

def get_website_text(session, website):

    if not website:
        return None, None, "missing_website"

    website = website.strip()

    if not website.startswith(("http://", "https://")):
        website = "https://" + website

    if not robots_allowed(session, website):
        return None, website, "robots_unavailable_or_disallowed"

    try:

        response = session.get(
            website,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT}
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        if "text/html" not in content_type:
            return None, website, "not_html"

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for tag in soup(
            ["script", "style", "noscript"]
        ):
            tag.decompose()

        text = soup.get_text(
            " ",
            strip=True
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        ).casefold()

        return text[:150000], response.url, "success"

    except requests.RequestException:
        return None, website, "request_failed"


# ----------------------------------------
# MATCH KEYWORDS
# ----------------------------------------

def find_keywords(text, keywords):

    matches = []

    for keyword in keywords:

        pattern = (
            r"(?<!\w)"
            + re.escape(keyword.casefold())
            + r"(?!\w)"
        )

        if re.search(pattern, text):
            matches.append(keyword)

    return matches


# ----------------------------------------
# CLASSIFY COMPANY
# ----------------------------------------

def classify_text(text):

    direct = find_keywords(
        text,
        DIRECT_KEYWORDS
    )

    indirect = find_keywords(
        text,
        INDIRECT_KEYWORDS
    )

    crop = find_keywords(
        text,
        CROP_KEYWORDS
    )

    if direct:

        return "direct", direct

    if indirect:

        return "indirect", indirect

    # Crop-only is a provisional classification.
    # Require at least two different crop terms.
    if len(crop) >= 2:

        return "crop_focused", crop

    return "unknown", crop


# ----------------------------------------
# SAVE ONE RESULT
# ----------------------------------------

def save_result(conn, result):

    conn.execute("""
        INSERT INTO company_relevance (
            discovery_id,
            company,
            relevance,
            matched_keywords,
            evidence_url,
            classification_status,
            checked_at
        )

        VALUES (?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(discovery_id)
        DO UPDATE SET
            company = excluded.company,
            relevance = excluded.relevance,
            matched_keywords = excluded.matched_keywords,
            evidence_url = excluded.evidence_url,
            classification_status = excluded.classification_status,
            checked_at = excluded.checked_at

    """, result)

    conn.commit()


# ----------------------------------------
# EXPORT CSV
# ----------------------------------------

def export_csv(conn):

    rows = conn.execute("""
        SELECT
            discovery_id,
            company,
            relevance,
            matched_keywords,
            evidence_url,
            classification_status,
            checked_at

        FROM company_relevance

        ORDER BY company
    """).fetchall()

    columns = [
        "discovery_id",
        "company",
        "relevance",
        "matched_keywords",
        "evidence_url",
        "classification_status",
        "checked_at"
    ]

    with CSV_PATH.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(file)

        writer.writerow(columns)

        for row in rows:
            writer.writerow(tuple(row))


# ----------------------------------------
# MAIN
# ----------------------------------------

def main():

    print("=" * 50)
    print("STEP 6: EQUIPMENT COMPANY CLASSIFICATION")
    print("=" * 50)

    conn = connect_database()

    try:

        create_table(conn)

        companies = conn.execute("""
            SELECT
                id,
                company,
                website
            FROM discovery_candidates
            WHERE source_name = ?
            ORDER BY id
        """, (SOURCE_NAME,)).fetchall()

        print("Companies to classify:", len(companies))

        completed = {
            row["discovery_id"]
            for row in conn.execute("""
                SELECT discovery_id
                FROM company_relevance
            """)
        }

        session = requests.Session()

        counts = Counter()

        try:

            for index, company in enumerate(
                companies,
                start=1
            ):

                company_id = company["id"]

                if company_id in completed:
                    print(
                        f"[{index}/{len(companies)}] "
                        f"Already processed: {company['company']}"
                    )
                    continue

                print(
                    f"\n[{index}/{len(companies)}] "
                    f"{company['company']}"
                )

                text, evidence_url, status = get_website_text(
                    session,
                    company["website"]
                )

                if text:

                    relevance, keywords = classify_text(text)

                else:

                    relevance = "unknown"
                    keywords = []

                counts[relevance] += 1

                result = (
                    company_id,
                    company["company"],
                    relevance,
                    " | ".join(keywords),
                    evidence_url,
                    status,
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                )

                save_result(conn, result)

                print("Classification:", relevance)
                print("Status:", status)
                print("Keywords:", keywords)

                # Respectful request interval.
                time.sleep(REQUEST_DELAY)

        finally:
            session.close()

        export_csv(conn)

        print("\n" + "=" * 50)
        print("CLASSIFICATION COMPLETE")
        print("=" * 50)

        total = conn.execute("""
            SELECT COUNT(*)
            FROM company_relevance
        """).fetchone()[0]

        print("Stored classifications:", total)

        print("\nNewly classified during this run:")

        for category, count in counts.items():
            print(f"{category}: {count}")

        print("\nCSV:", CSV_PATH)
        print("Database:", DB_PATH)

    finally:
        conn.close()


if __name__ == "__main__":
    main()