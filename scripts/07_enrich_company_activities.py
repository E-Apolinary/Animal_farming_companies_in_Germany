import csv
import re
import sqlite3
import time

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


# ---------------------------------------
# CONFIGURATION
# ---------------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"

CSV_PATH = ROOT / "data/processed/company_activity_enrichment.csv"

CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

USER_AGENT = "AnimalFarmingGermanyResearch/1.0"

TIMEOUT = 15
REQUEST_DELAY = 1.5

# Homepage + up to three additional pages
MAX_INTERNAL_PAGES = 3

SOURCE_NAME = "VDMA Landtechnik Member Directory"


# ---------------------------------------
# KEYWORDS
# ---------------------------------------

DIRECT_TERMS = [
    "stalltechnik",
    "stalleinrichtung",
    "stallausrüstung",
    "melktechnik",
    "melkroboter",
    "melkanlage",
    "fütterungsanlage",
    "fütterungstechnik",
    "herdenmanagement",
    "rinderhaltung",
    "schweinehaltung",
    "geflügelhaltung",
    "nutztierhaltung",
    "tierhaltung",
    "livestock farming",
    "livestock equipment",
    "dairy farming",
    "milking system",
    "animal feeding",
    "poultry farming",
    "pig farming",
    "barn equipment",
    "entmistung",
]

INDIRECT_TERMS = [
    "futterernte",
    "futtererntetechnik",
    "futterproduktion",
    "futteraufbereitung",
    "silagetechnik",
    "grünlandtechnik",
    "forage harvesting",
    "forage equipment",
    "feed processing",
    "feed production",
    "baling equipment",
]

CROP_TERMS = [
    "bodenbearbeitung",
    "pflanzenschutztechnik",
    "sätechnik",
    "saattechnik",
    "ackerbau",
    "pflanzenbau",
    "soil cultivation",
    "crop protection",
    "seed drilling",
    "combine harvester",
]

# Useful link labels or URL paths
PAGE_TERMS = [
    "produkt",
    "product",
    "solution",
    "lösung",
    "loesung",
    "anwendung",
    "application",
    "branche",
    "industry",
    "industries",
    "landwirtschaft",
    "agriculture",
    "tierhaltung",
    "livestock",
    "dairy",
    "feeding",
    "milking",
]


# ---------------------------------------
# DATABASE SETUP
# ---------------------------------------

def connect_database():

    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn


def create_table(conn):

    conn.execute("""
        CREATE TABLE IF NOT EXISTS
        company_activity_enrichment (

            discovery_id INTEGER PRIMARY KEY,

            company TEXT,

            classification TEXT,

            direct_keywords TEXT,

            indirect_keywords TEXT,

            crop_keywords TEXT,

            evidence_urls TEXT,

            pages_analyzed INTEGER,

            status TEXT,

            enriched_at TEXT,

            FOREIGN KEY(discovery_id)
                REFERENCES discovery_candidates(id)
        )
    """)

    conn.commit()


# ---------------------------------------
# URL HELPERS
# ---------------------------------------

def normalize_url(url):

    if not url:
        return None

    url = str(url).strip()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    return urldefrag(url)[0]


def hostname(url):

    if not url:
        return None

    return urlparse(url).hostname


def same_website(url1, url2):

    h1 = hostname(url1)
    h2 = hostname(url2)

    if not h1 or not h2:
        return False

    return (
        h1.lower().removeprefix("www.")
        == h2.lower().removeprefix("www.")
    )


# ---------------------------------------
# ROBOTS.TXT
# ---------------------------------------

robots_cache = {}


def robots_allowed(session, url):

    parsed = urlparse(url)

    origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin not in robots_cache:

        robots_url = origin + "/robots.txt"

        try:

            response = session.get(
                robots_url,
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT}
            )

            if response.status_code == 404:

                robots_cache[origin] = True

            elif response.status_code == 200:

                parser = RobotFileParser()
                parser.parse(response.text.splitlines())

                robots_cache[origin] = parser

            else:

                robots_cache[origin] = False

        except requests.RequestException:

            robots_cache[origin] = False

    rule = robots_cache[origin]

    if rule is True:
        return True

    if rule is False:
        return False

    return rule.can_fetch(USER_AGENT, url)


# ---------------------------------------
# DOWNLOAD PUBLIC HTML
# ---------------------------------------

def download_page(session, url):

    if not robots_allowed(session, url):
        return None, "robots_unavailable_or_disallowed"

    try:

        # Disable automatic redirects so each destination
        # can be checked before being requested.
        response = session.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=False
        )

        # Follow a small number of ordinary redirects.
        redirects = 0

        while response.is_redirect and redirects < 5:

            location = response.headers.get("Location")

            if not location:
                return None, "invalid_redirect"

            next_url = urljoin(response.url, location)

            if not robots_allowed(session, next_url):
                return None, "robots_unavailable_or_disallowed"

            response = session.get(
                next_url,
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=False
            )

            redirects += 1

        if response.is_redirect:
            return None, "too_many_redirects"

        response.raise_for_status()

        if "text/html" not in response.headers.get(
            "Content-Type", ""
        ).lower():
            return None, "not_html"

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        return (soup, response.url), "success"

    except requests.RequestException:

        return None, "request_failed"


# ---------------------------------------
# EXTRACT TEXT
# ---------------------------------------

def extract_text(soup):

    for element in soup(
        ["script", "style", "noscript"]
    ):
        element.decompose()

    text = soup.get_text(
        " ",
        strip=True
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.casefold()[:150000]


# ---------------------------------------
# FIND RELEVANT INTERNAL LINKS
# ---------------------------------------

def find_internal_links(soup, base_url):

    candidates = []

    seen = set()

    for link in soup.find_all("a", href=True):

        href = link["href"].strip()

        if href.startswith((
            "#",
            "mailto:",
            "tel:",
            "javascript:"
        )):
            continue

        url = normalize_url(
            urljoin(base_url, href)
        )

        if not url:
            continue

        if not same_website(base_url, url):
            continue

        if url in seen:
            continue

        seen.add(url)

        link_text = link.get_text(
            " ",
            strip=True
        ).casefold()

        combined = (
            link_text + " " + url.casefold()
        )

        score = sum(
            term in combined
            for term in PAGE_TERMS
        )

        if score > 0:

            candidates.append(
                (score, url)
            )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True
    )

    return [
        url
        for _, url in candidates
    ]


# ---------------------------------------
# KEYWORD MATCHING
# ---------------------------------------

def match_keywords(text, terms):

    matches = set()

    for term in terms:

        pattern = (
            r"(?<!\w)"
            + re.escape(term.casefold())
            + r"(?!\w)"
        )

        if re.search(pattern, text):
            matches.add(term)

    return matches


# ---------------------------------------
# ENRICH ONE COMPANY
# ---------------------------------------

def enrich_company(session, company):

    website = normalize_url(company["website"])

    if not website:

        return {
            "classification": "unknown",
            "direct": set(),
            "indirect": set(),
            "crop": set(),
            "urls": [],
            "pages": 0,
            "status": "missing_website"
        }

    result = {
        "classification": "unknown",
        "direct": set(),
        "indirect": set(),
        "crop": set(),
        "urls": [],
        "pages": 0,
        "status": "no_pages_analyzed"
    }

    downloaded, status = download_page(
        session,
        website
    )

    if downloaded is None:

        result["status"] = status

        return result

    homepage_soup, final_url = downloaded

    internal_links = find_internal_links(
        homepage_soup,
        final_url
    )

    # Homepage and up to MAX_INTERNAL_PAGES.
    pages = [(homepage_soup, final_url)]

    for url in internal_links[:MAX_INTERNAL_PAGES]:

        time.sleep(REQUEST_DELAY)

        downloaded, _ = download_page(
            session,
            url
        )

        if downloaded is not None:

            pages.append(downloaded)

    for soup, url in pages:

        text = extract_text(soup)

        direct = match_keywords(
            text,
            DIRECT_TERMS
        )

        indirect = match_keywords(
            text,
            INDIRECT_TERMS
        )

        crop = match_keywords(
            text,
            CROP_TERMS
        )

        result["direct"].update(direct)
        result["indirect"].update(indirect)
        result["crop"].update(crop)

        if direct or indirect or crop:
            result["urls"].append(url)

        result["pages"] += 1

    if result["direct"]:

        result["classification"] = "direct"

    elif result["indirect"]:

        result["classification"] = "indirect"

    elif len(result["crop"]) >= 2:

        result["classification"] = "crop_focused"

    result["status"] = "success"

    return result


# ---------------------------------------
# SAVE RESULTS
# ---------------------------------------

def save_result(conn, company, result):

    conn.execute("""
        INSERT INTO company_activity_enrichment (
            discovery_id,
            company,
            classification,
            direct_keywords,
            indirect_keywords,
            crop_keywords,
            evidence_urls,
            pages_analyzed,
            status,
            enriched_at
        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(discovery_id)
        DO UPDATE SET
            company = excluded.company,
            classification = excluded.classification,
            direct_keywords = excluded.direct_keywords,
            indirect_keywords = excluded.indirect_keywords,
            crop_keywords = excluded.crop_keywords,
            evidence_urls = excluded.evidence_urls,
            pages_analyzed = excluded.pages_analyzed,
            status = excluded.status,
            enriched_at = excluded.enriched_at

    """, (
        company["id"],
        company["company"],
        result["classification"],
        " | ".join(sorted(result["direct"])),
        " | ".join(sorted(result["indirect"])),
        " | ".join(sorted(result["crop"])),
        " | ".join(result["urls"]),
        result["pages"],
        result["status"],
        datetime.now(timezone.utc).isoformat()
    ))

    conn.commit()


# ---------------------------------------
# EXPORT CSV
# ---------------------------------------

def export_csv(conn):

    rows = conn.execute("""
        SELECT *
        FROM company_activity_enrichment
        ORDER BY company
    """).fetchall()

    if not rows:
        return

    with CSV_PATH.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.writer(file)

        writer.writerow(rows[0].keys())

        for row in rows:
            writer.writerow(tuple(row))


# ---------------------------------------
# MAIN
# ---------------------------------------

def main():

    print("=" * 50)
    print("STEP 7: COMPANY ACTIVITY ENRICHMENT")
    print("=" * 50)

    conn = connect_database()

    try:

        create_table(conn)

        # Only VDMA companies that were successfully
        # downloaded but remained unclassified.
        companies = conn.execute("""
            SELECT
                d.id,
                d.company,
                d.website

            FROM discovery_candidates d

            JOIN company_relevance r
                ON d.id = r.discovery_id

            WHERE d.source_name = ?
              AND r.relevance = 'unknown'
              AND r.classification_status = 'success'

            ORDER BY d.id
        """, (SOURCE_NAME,)).fetchall()

        print("Companies eligible:", len(companies))

        completed = {
            row["discovery_id"]
            for row in conn.execute("""
                SELECT discovery_id
                FROM company_activity_enrichment
            """)
        }

        session = requests.Session()

        try:

            for index, company in enumerate(
                companies,
                start=1
            ):

                if company["id"] in completed:
                    print(
                        f"[{index}/{len(companies)}] "
                        f"Already processed: {company['company']}"
                    )
                    continue

                print(
                    f"\n[{index}/{len(companies)}] "
                    f"{company['company']}"
                )

                result = enrich_company(
                    session,
                    company
                )

                save_result(
                    conn,
                    company,
                    result
                )

                print(
                    "Classification:",
                    result["classification"]
                )

                print(
                    "Pages analyzed:",
                    result["pages"]
                )

                print(
                    "Status:",
                    result["status"]
                )

                time.sleep(REQUEST_DELAY)

        finally:
            session.close()

        export_csv(conn)

        print("\nEnrichment complete.")
        print("CSV:", CSV_PATH)

    finally:
        conn.close()


if __name__ == "__main__":
    main()