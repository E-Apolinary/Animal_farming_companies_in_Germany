"""
STEP 19: Livestock producer discovery.

Pages through the IMA (information.medien.agrar) directory of livestock
project farms, keeps only entries whose name shows a corporate legal
form (GmbH, AG, eG, KG, ...), opens each profile to read postcode, city,
federal state and website, and saves the results to a CSV file and to
the `discovery_candidates` table of the existing project database.
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


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
CSV_PATH = ROOT / "data/raw/livestock_production_companies.csv"

SOURCE_URL = "https://ima-agrar.de/einsichten-in-die-tierhaltung/projektbetriebe"
SOURCE_NAME = "IMA Livestock Production Directory"
SECTOR = "Livestock Farming - Relevance Unverified"
DESCRIPTION = (
    "Livestock-production project participant. Corporate structure "
    "identified by name; animal species and employer scale require "
    "verification."
)

# Column order for both the CSV file and the database insert.
FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]

# Columns that form the table's unique key (used in ON CONFLICT).
KEY_FIELDS = ("source_name", "company", "address")

# Columns always overwritten on conflict. email / phone are in neither
# list because this source does not publish them.
UPDATE_FIELDS = (
    "sector", "city", "postal_code", "description", "source_url",
    "collected_at",
)

# Columns overwritten only when the new value is not empty, so a profile
# without a website never wipes a website already stored.
KEEP_IF_EMPTY_FIELDS = ("website",)

# The directory shows 20 entries per page, selected with ?start=<offset>.
PAGE_SIZE = 20

# Safety limit; the loop normally stops when a page is not full.
MAX_PAGES = 20

# Pause after every request to be polite to the server.
REQUEST_DELAY = 0.3

# Save the CSV every N new records, so a crash keeps most of the work
# without rewriting the whole file after every single profile.
CHECKPOINT_EVERY = 10

USER_AGENT = "Mozilla/5.0 (compatible; AnimalFarmingGermany/1.0)"


# --------------------------------------------------
# FILTERS
# --------------------------------------------------

# A legal-form word in the name marks a company rather than a family farm.
COMPANY_PATTERN = re.compile(
    r"\b(GmbH|gGmbH|AG|e\.?\s*G\.?|KG|mbH|Genossenschaft)\b",
    flags=re.IGNORECASE,
)

# Small farms, holiday farms, farm shops and butchers are out of scope.
EXCLUDE_TERMS = (
    "bauernhof", "ferienhof", "hofladen", "landmetzgerei", "schulbauernhof",
)

POSTCODE_RE = re.compile(r"\d{5}")
WEBSITE_LABEL_RE = re.compile(r"Betriebs-Website", re.IGNORECASE)


def eligible_company(name):
    """True if the name has a legal form and no excluded term."""
    if any(term in name.casefold() for term in EXCLUDE_TERMS):
        return False

    return bool(COMPANY_PATTERN.search(name))


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def clean(value):
    """Collapse all whitespace to single spaces; None becomes ''."""
    return " ".join(str(value or "").split())


def fetch_soup(session, url, params=None):
    """Download a page, pause briefly, and return it parsed as HTML."""
    response = session.get(url, params=params, timeout=45)
    response.raise_for_status()
    time.sleep(REQUEST_DELAY)

    return BeautifulSoup(response.text, "html.parser")


def extract_field(text, field):
    """Return the value of a 'Field: value' line in text, or ''."""
    # (?im): case-insensitive, and ^ / $ match at every line.
    match = re.search(rf"(?im)^\s*{re.escape(field)}\s*:\s*(.+)$", text)
    return clean(match.group(1)) if match else ""


def is_http(href):
    return href.startswith(("http://", "https://"))


# --------------------------------------------------
# COLLECT DIRECTORY LINKS
# --------------------------------------------------

def collect_directory_links(session):
    """Page through the directory and return eligible profile links."""
    candidates = []
    seen_urls = set()

    for page_number in range(MAX_PAGES):
        offset = page_number * PAGE_SIZE

        # The first page has no ?start parameter.
        soup = fetch_soup(session, SOURCE_URL, params={"start": offset} if offset else None)
        container = soup.select_one("#jf_results")

        if container is None:
            raise RuntimeError("Directory results container not found.")

        cards = container.select('a[href*="/einsichten-tierhaltung/"]')

        if not cards:
            break

        new_links = 0

        for card in cards:
            heading = card.find(["h2", "h3", "h4", "h5"])

            if heading is None:
                continue

            company = clean(heading.get_text(" ", strip=True))
            profile_url = urljoin(SOURCE_URL, card.get("href", ""))

            if not eligible_company(company) or profile_url in seen_urls:
                continue

            seen_urls.add(profile_url)
            candidates.append({"company": company, "profile_url": profile_url})
            new_links += 1

        print(
            f"Directory page {page_number + 1}: {len(cards)} listings; "
            f"{new_links} new corporate candidates"
        )

        # A page that is not full is the last page.
        if len(cards) < PAGE_SIZE:
            break

    return candidates


# --------------------------------------------------
# EXTRACT COMPANY PROFILE
# --------------------------------------------------

def find_website(soup):
    """
    Find the farm's website on a profile page.

    1. A http(s) link whose text is "Betriebs-Website" or contains "www.".
    2. Otherwise, a http(s) link next to a "Betriebs-Website" label (in
       the label's parent or grandparent element).
    """
    for link in soup.select("a[href]"):
        href = link["href"].strip()
        label = link.get_text(" ", strip=True).casefold()

        if is_http(href) and ("betriebs-website" in label or "www." in label):
            return href

    for label in soup.find_all(string=WEBSITE_LABEL_RE):
        parent = label.parent

        for scope in (parent, parent.parent if parent else None):
            link = scope.find("a", href=True) if scope else None

            if link and is_http(link["href"]):
                return link["href"]

    return ""


def extract_profile(session, candidate, collected_at):
    """Parse one profile page into a record, or None if not eligible."""
    soup = fetch_soup(session, candidate["profile_url"])

    # Prefer the profile's own heading over the directory card name.
    heading = soup.find("h1")
    company = clean(heading.get_text(" ", strip=True)) if heading else candidate["company"]

    if not eligible_company(company):
        return None

    # Keep line breaks so each "Field: value" sits on its own line.
    text = soup.get_text("\n", strip=True)

    postal_code = extract_field(text, "PLZ")
    city = extract_field(text, "Ort")
    state = extract_field(text, "Bundesland")

    # Keep only valid German postcodes; never guess one.
    if not POSTCODE_RE.fullmatch(postal_code):
        postal_code = ""

    description = DESCRIPTION + (f" Federal state: {state}." if state else "")

    return {
        "company": company,
        "sector": SECTOR,
        "city": city,
        "postal_code": postal_code,
        "address": f"{postal_code} {city}".strip(),
        "website": find_website(soup),
        "email": "",
        "phone": "",
        "description": description,
        "source_name": SOURCE_NAME,
        "source_url": candidate["profile_url"],
        "collected_at": collected_at,
    }


# --------------------------------------------------
# SAVE CSV
# --------------------------------------------------

def save_csv(records):
    """Write records to CSV (utf-8-sig so Excel shows umlauts correctly)."""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


# --------------------------------------------------
# COLLECT PROFILES
# --------------------------------------------------

def collect(session):
    """Visit every candidate profile and return unique records."""
    links = collect_directory_links(session)

    print()
    print("Corporate candidates:", len(links))

    records = []
    seen = set()  # (company, address) pairs already collected

    # One timestamp for the whole run, so all records share it.
    collected_at = datetime.now(timezone.utc).isoformat()

    for index, candidate in enumerate(links, 1):
        try:
            record = extract_profile(session, candidate, collected_at)
        except requests.RequestException as error:
            print(f"Profile {index} failed: {error}")
            continue

        if record is None:
            continue

        key = (record["company"].casefold(), record["address"].casefold())

        if key in seen:
            continue

        seen.add(key)
        records.append(record)
        print(f"Profile {index}/{len(links)}: {record['company']}")

        # Periodic checkpoint; main() writes the complete file at the end.
        if len(records) % CHECKPOINT_EVERY == 0:
            save_csv(records)

    return records


# --------------------------------------------------
# EXISTING DATABASE UPSERT
# --------------------------------------------------

def save_database(records):
    """
    Insert records, or update them if they already exist.

    The SQL is built from the field lists above. Named placeholders
    (:company, ...) let sqlite read values straight from each record
    dict, and executemany sends all rows in one call.
    """
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    columns = ", ".join(FIELDS)
    placeholders = ", ".join(f":{field}" for field in FIELDS)
    updates = ", ".join(
        [f"{field} = excluded.{field}" for field in UPDATE_FIELDS]
        + [
            f"{field} = CASE WHEN excluded.{field} != '' "
            f"THEN excluded.{field} ELSE discovery_candidates.{field} END"
            for field in KEEP_IF_EMPTY_FIELDS
        ]
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


# --------------------------------------------------
# REPORT
# --------------------------------------------------

def print_report(records):
    """Print how complete the collected data is."""

    def count(field):
        return sum(bool(r[field]) for r in records)

    print()
    print("=" * 45)
    print("LIVESTOCK PRODUCTION DISCOVERY REPORT")
    print("=" * 45)
    print("Corporate candidates:", len(records))
    print("With websites:", count("website"))
    print("With cities:", count("city"))
    print(
        "Unique company/location pairs:",
        len({(r["company"].casefold(), r["address"].casefold()) for r in records}),
    )
    print("=" * 45)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 19: LIVESTOCK PRODUCTION DISCOVERY")
    print("=" * 45)

    # A session reuses the TCP connection across all requests.
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        records = collect(session)

    if not records:
        raise RuntimeError("No corporate livestock candidates collected.")

    save_csv(records)
    save_database(records)
    print_report(records)


if __name__ == "__main__":
    main()
