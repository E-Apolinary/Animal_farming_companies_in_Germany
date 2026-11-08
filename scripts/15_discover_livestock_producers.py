"""
STEP 15: Discover corporate livestock producers.

Source: IMA (information.medien.agrar) directory of livestock farms
taking part in its "Einsichten in die Tierhaltung" project.

The directory is paged (20 farms per page). Only farms whose name shows
a corporate legal form (GmbH, AG, eG, KG, ...) are kept, because family
farms are rarely employers. Each kept farm's profile page supplies
postcode, city, federal state and website. Step 19 later checks the
websites to find out which animals each farm keeps.
"""

import re
import time
from urllib.parse import urljoin

import requests

from common import (
    POSTCODE_RE, RAW_DIR, clean, dedupe, fetch_soup, make_record,
    new_session, print_banner, print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "livestock_production_companies.csv"
SOURCE_URL = "https://ima-agrar.de/einsichten-in-die-tierhaltung/projektbetriebe"
SOURCE_NAME = "IMA Livestock Production Directory"
SECTOR = "Livestock Farming - Relevance Unverified"
DESCRIPTION = (
    "Livestock-production project participant. Corporate structure identified "
    "by name; animal species and employer scale require verification."
)

PAGE_SIZE = 20       # entries per directory page (?start=<offset>)
MAX_PAGES = 20       # safety limit; a page that is not full ends the loop
REQUEST_DELAY = 0.3  # pause after every request
CHECKPOINT_EVERY = 10

# A legal-form word marks a company rather than a family farm.
COMPANY_RE = re.compile(r"\b(GmbH|gGmbH|AG|e\.?\s*G\.?|KG|mbH|Genossenschaft)\b", re.IGNORECASE)

# Small farms, holiday farms, farm shops and butchers are out of scope.
EXCLUDE_TERMS = ("bauernhof", "ferienhof", "hofladen", "landmetzgerei", "schulbauernhof")

WEBSITE_LABEL_RE = re.compile(r"Betriebs-Website", re.IGNORECASE)


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def is_corporate(name):
    """True if the name has a legal form and no excluded term."""
    return (
        not any(term in name.casefold() for term in EXCLUDE_TERMS)
        and bool(COMPANY_RE.search(name))
    )


def fetch(session, url, params=None):
    """fetch_soup followed by a short, polite pause."""
    soup = fetch_soup(url, session, params=params)
    time.sleep(REQUEST_DELAY)
    return soup


def profile_field(text, field):
    """Value of a 'Field: value' line in the profile text, or ''."""
    # (?im): case-insensitive, and ^ / $ match at every line.
    match = re.search(rf"(?im)^\s*{re.escape(field)}\s*:\s*(.+)$", text)
    return clean(match.group(1)) if match else ""


def is_http(href):
    return href.startswith(("http://", "https://"))


def find_website(soup):
    """
    The farm's own website on a profile page.

    1. An http(s) link whose text is "Betriebs-Website" or contains "www.".
    2. Otherwise an http(s) link next to a "Betriebs-Website" label (in
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


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def directory_candidates(session):
    """Page through the directory and return corporate profile links."""
    candidates, seen_urls = [], set()

    for page_number in range(MAX_PAGES):
        offset = page_number * PAGE_SIZE
        soup = fetch(session, SOURCE_URL, params={"start": offset} if offset else None)
        container = soup.select_one("#jf_results")

        if container is None:
            raise RuntimeError("Directory results container not found.")

        cards = container.select('a[href*="/einsichten-tierhaltung/"]')

        if not cards:
            break

        new_links = 0

        for card in cards:
            heading = card.find(["h2", "h3", "h4", "h5"])
            company = clean(heading.get_text(" ", strip=True)) if heading else ""
            url = urljoin(SOURCE_URL, card.get("href", ""))

            if company and is_corporate(company) and url not in seen_urls:
                seen_urls.add(url)
                candidates.append({"company": company, "profile_url": url})
                new_links += 1

        print(f"Directory page {page_number + 1}: {len(cards)} listings; {new_links} corporate")

        if len(cards) < PAGE_SIZE:  # last page
            break

    return candidates


def extract_profile(session, candidate):
    """Parse one profile page into a record, or None if not corporate."""
    soup = fetch(session, candidate["profile_url"])

    # Prefer the profile's own heading over the directory card name.
    heading = soup.find("h1")
    company = clean(heading.get_text(" ", strip=True)) if heading else candidate["company"]

    if not is_corporate(company):
        return None

    # Line breaks keep each "Field: value" on its own line.
    text = soup.get_text("\n", strip=True)
    postal_code = profile_field(text, "PLZ")
    city = profile_field(text, "Ort")
    state = profile_field(text, "Bundesland")

    if not POSTCODE_RE.fullmatch(postal_code):
        postal_code = ""

    return make_record(
        company=company,
        sector=SECTOR,
        city=city,
        postal_code=postal_code,
        address=f"{postal_code} {city}".strip(),
        website=find_website(soup),
        description=DESCRIPTION + (f" Federal state: {state}." if state else ""),
        source_name=SOURCE_NAME,
        source_url=candidate["profile_url"],
    )


def collect(session):
    candidates = directory_candidates(session)
    print("\nCorporate candidates:", len(candidates))
    records = []

    for index, candidate in enumerate(candidates, 1):
        try:
            record = extract_profile(session, candidate)
        except requests.RequestException as error:
            print(f"Profile {index} failed: {error}")
            continue

        if record is None:
            continue

        records.append(record)
        print(f"Profile {index}/{len(candidates)}: {record['company']}")

        # A crash keeps most of the work; main() writes the full file.
        if len(records) % CHECKPOINT_EVERY == 0:
            save_csv(dedupe(records), CSV_PATH)

    return dedupe(records)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 15: LIVESTOCK PRODUCER DISCOVERY")

    with new_session() as session:
        records = collect(session)

    if not records:
        raise RuntimeError("No corporate livestock candidates collected.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("LIVESTOCK PRODUCER DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
