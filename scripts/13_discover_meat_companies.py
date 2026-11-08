import csv
import re
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
CSV_PATH = ROOT / "data/raw/vdf_meat_companies.csv"

SOURCE_URL = "https://www.v-d-f.de/mitglieder-uebersicht/mitglieder/mg-schlachtung"
SOURCE_NAME = "VDF Meat Industry Member Directory - Slaughtering"
SECTOR = "Meat Processing and Slaughtering"
DESCRIPTION = "VDF member listed in the slaughtering category."

FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]

LOCATION_RE = re.compile(r"^(\d{5})\s+(.+)$")
IGNORED_PREFIXES = ("Telefax:", "E-Mail:", "Internet:")


# -----------------------------------
# HELPERS
# -----------------------------------

def clean(value):
    return " ".join(str(value).split())


def fetch(session, url):
    response = session.get(url, timeout=45)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def link_href(element, selector):
    link = element.select_one(selector)
    return link.get("href", "").strip() if link else ""


# -----------------------------------
# EXTRACT COMPANY PROFILE
# -----------------------------------

def extract_profile(session, url, collected_at):
    article = fetch(session, url).select_one(".article.unternehmen")
    heading = article.select_one("h1") if article else None

    if heading is None:
        return None

    street = location = phone = email = website = ""

    # Address and contact details live in top-level div elements.
    for element in article.find_all("div", recursive=False):
        value = clean(element.get_text(" ", strip=True))

        if not value:
            continue
        if LOCATION_RE.match(value):
            location = value
        elif value.startswith("Telefon:"):
            phone = clean(value.removeprefix("Telefon:"))
        elif value.startswith("Kontakt:"):
            email = (
                link_href(element, "a[href^='mailto:']")
                .removeprefix("mailto:")
                .split("?")[0]
            )
        elif value.startswith("Webseite:"):
            website = link_href(element, "a[href^='http']")
        elif not street and not value.startswith(IGNORED_PREFIXES):
            street = value

    # Keep German establishments only (5-digit postal code).
    match = LOCATION_RE.match(location)

    if not match:
        return None

    return {
        "company": clean(heading.get_text(" ", strip=True)),
        "sector": SECTOR,
        "city": clean(match.group(2)),
        "postal_code": match.group(1),
        "address": ", ".join(part for part in (street, location) if part),
        "website": website,
        "email": email,
        "phone": phone,
        "description": DESCRIPTION,
        "source_name": SOURCE_NAME,
        "source_url": url,
        "collected_at": collected_at,
    }


# -----------------------------------
# COLLECT COMPANIES
# -----------------------------------

def collect():
    records = []
    seen = set()
    collected_at = datetime.now(timezone.utc).isoformat()

    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (compatible; AnimalFarmingGermanyResearch/1.0)"
    )

    print("Opening VDF slaughtering directory...")

    cards = fetch(session, SOURCE_URL).select(".item-wrapper")
    print("Directory entries found:", len(cards))

    if not cards:
        raise RuntimeError("No VDF company listings found.")

    for index, card in enumerate(cards, start=1):
        name = card.select_one(".item-titel")
        link = card.select_one("a.more[href]")

        if not name or not link:
            continue

        print(f"[{index}/{len(cards)}] {clean(name.get_text(' ', strip=True))}")

        try:
            record = extract_profile(
                session, urljoin(SOURCE_URL, link["href"]), collected_at
            )
        except requests.RequestException as error:
            print("  Request failed:", error)
            continue
        finally:
            time.sleep(0.5)

        if record is None:
            print("  Skipped: incomplete profile")
            continue

        # Exclude explicitly local butcher shops.
        if "landmetzgerei" in record["company"].casefold():
            print("  Skipped: local butcher")
            continue

        key = (record["company"].casefold(), record["address"].casefold())

        if key not in seen:
            seen.add(key)
            records.append(record)

    return records


# -----------------------------------
# SAVE
# -----------------------------------

def save_csv(records):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)

    print("CSV saved:", CSV_PATH)


def save_database(records):
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    columns = ", ".join(FIELDS)
    placeholders = ", ".join(f":{field}" for field in FIELDS)
    updates = ", ".join(
        f"{field} = excluded.{field}"
        for field in FIELDS
        if field not in ("source_name", "company", "address")
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            f"""
            INSERT INTO discovery_candidates ({columns})
            VALUES ({placeholders})
            ON CONFLICT (source_name, company, address)
            DO UPDATE SET {updates}
            """,
            records,
        )

    print("Database updated successfully.")


# -----------------------------------
# REPORT
# -----------------------------------

def report(records):
    def count(field):
        return sum(bool(r[field]) for r in records)

    print()
    print("=" * 45)
    print("MEAT INDUSTRY DISCOVERY REPORT")
    print("=" * 45)
    print("Companies collected:", len(records))
    print("Unique company names:", len({r["company"].casefold() for r in records}))
    print("Companies with websites:", count("website"))
    print("Companies with cities:", count("city"))
    print("Companies with emails:", count("email"))
    print("=" * 45)


# -----------------------------------
# MAIN
# -----------------------------------

def main():
    print("=" * 45)
    print("ANIMAL FARMING GERMANY")
    print("STEP 13: MEAT COMPANY DISCOVERY")
    print("=" * 45)

    records = collect()

    if not records:
        raise RuntimeError("No German meat companies extracted.")

    save_csv(records)
    save_database(records)
    report(records)

    print("\nMeat company discovery completed.")


if __name__ == "__main__":
    main()
