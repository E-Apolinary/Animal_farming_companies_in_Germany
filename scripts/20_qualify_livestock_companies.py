"""
STEP 20: Livestock company qualification.

Takes the IMA livestock candidates collected in step 19, visits each
company website (homepage plus up to two relevant sub-pages), and looks
for keywords that show which kind of livestock the company keeps (pigs,
cattle, dairy, poultry, sheep/goats). A clear result replaces the
placeholder sector in `discovery_candidates`; unclear results leave the
database unchanged. Every check is written to an evidence CSV report.
"""

import csv
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
REPORT_PATH = ROOT / "data/processed/livestock_qualification.csv"

SOURCE_NAME = "IMA Livestock Production Directory"
UNKNOWN_SECTOR = "Livestock Farming - Relevance Unverified"
MIXED_SECTOR = "Mixed Livestock Production"
CROP_ONLY_SECTOR = "Out of Scope - Crop Only"

# Sub-pages visited per website in addition to the homepage.
MAX_EXTRA_PAGES = 2

# Pause before each sub-page request to be polite to the server.
REQUEST_DELAY = 0.3
TIMEOUT = 20

# Fewer characters than this is too little text to judge a company by.
MIN_CONTENT_LENGTH = 100

USER_AGENT = "Mozilla/5.0 (compatible; AnimalFarmingGermany/1.0)"

# Column order of the evidence CSV report.
REPORT_FIELDS = [
    "company", "website", "previous_sector", "classification", "status",
    "evidence", "evidence_urls",
]

# Page parts that are mostly menus, footers or scripts, whose keywords
# say nothing about what the company actually does.
NOISE_SELECTOR = "script, style, nav, footer, header, noscript, form, aside"

HTML_TYPES = ("text/html", "application/xhtml+xml")


# --------------------------------------------------
# LIVESTOCK CLASSIFICATION RULES
# --------------------------------------------------

# Keywords (German and English) that show a livestock activity.
KEYWORDS = {
    "Pig Production": [
        "schweinemast", "ferkelerzeugung", "ferkelproduktion",
        "sauenhaltung", "schweinezucht", "schweinehaltung",
        "pig farming", "pig production", "sow farming",
    ],
    "Cattle Production": [
        "rindermast", "bullenmast", "rinderhaltung", "mutterkuhhaltung",
        "rinderaufzucht", "rinderzucht", "beef cattle", "cattle farming",
        "cattle breeding",
    ],
    "Dairy Farming": [
        "milchviehhaltung", "milchproduktion", "milcherzeugung",
        "milchviehbetrieb", "milchkuhhaltung", "dairy farming",
        "dairy herd", "milk production",
    ],
    "Poultry Production": [
        "geflügelhaltung", "geflügelmast", "hähnchenmast", "putenmast",
        "legehennenhaltung", "eierproduktion", "bruteierproduktion",
        "poultry farming", "poultry production", "egg production",
    ],
    "Sheep and Goat Production": [
        "schafhaltung", "schafzucht", "schafmast", "ziegenhaltung",
        "ziegenzucht", "sheep farming", "goat farming",
    ],
}

# Compiled once: sector -> [(keyword, whole-word pattern), ...].
# The keyword itself is what the evidence report shows.
PATTERNS = {
    sector: [
        (keyword, re.compile(rf"\b{keyword}\b", re.IGNORECASE))
        for keyword in keywords
    ]
    for sector, keywords in KEYWORDS.items()
}

# These must explicitly say that crop farming is the ONLY activity.
CROP_ONLY_PATTERNS = [
    re.compile(pattern)
    for pattern in (
        r"\bausschließlich(?:er|e|es)?\s+ackerbau\b",
        r"\breiner\s+ackerbaubetrieb\b",
        r"\bspezialisiert\s+ausschließlich\s+auf\s+ackerbau\b",
        r"\bexclusively\s+crop\s+farming\b",
        r"\bcrop[- ]only\s+farm\b",
    )
]

# Link text or URL path containing one of these marks a sub-page that
# probably describes the farm's activities.
RELEVANT_LINK_TERMS = (
    "tierhaltung", "tierproduktion", "landwirtschaft", "betrieb",
    "produktion", "schweine", "rinder", "milchvieh", "gefluegel",
    "geflügel", "ueber-uns", "über-uns", "about", "farming", "livestock",
    "production",
)


# --------------------------------------------------
# WEBSITE HELPERS
# --------------------------------------------------

def normalize_url(url):
    """Add https:// to bare domains; empty input stays ''."""
    url = (url or "").strip()

    if not url or url.startswith(("http://", "https://")):
        return url

    return "https://" + url


def clean_text(text):
    """Collapse all whitespace to single spaces; None becomes ''."""
    return " ".join((text or "").split())


def relevant_links(container, page_url):
    """Return same-site links whose text or path looks relevant, in order."""
    base_host = (urlparse(page_url).hostname or "").lower()
    links = []

    for link in container.select("a[href]"):
        href = link["href"].strip()

        if not href:
            continue

        target = urljoin(page_url, href)
        parsed = urlparse(target)

        # Only follow http(s) pages on the same company website.
        if (
            parsed.scheme not in ("http", "https")
            or (parsed.hostname or "").lower() != base_host
        ):
            continue

        label = f"{link.get_text(' ', strip=True)} {parsed.path}".casefold()

        if any(term in label for term in RELEVANT_LINK_TERMS):
            links.append(target)

    # dict.fromkeys removes duplicates while keeping the original order.
    return list(dict.fromkeys(links))


def extract_page(session, url):
    """
    Download a page and return (main text, relevant same-site links).

    Non-HTML responses (PDFs, images, ...) return ('', []).
    """
    response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()

    if not any(kind in content_type for kind in HTML_TYPES):
        return "", []

    soup = BeautifulSoup(response.text, "html.parser")

    for element in soup.select(NOISE_SELECTOR):
        element.decompose()

    # Prefer <main>; fall back to the whole <body>.
    container = soup.find("main") or soup.body

    if container is None:
        return "", []

    # response.url is the final address after redirects, so relative
    # links and the same-site check use the real host.
    text = clean_text(container.get_text(" ", strip=True))
    return text, relevant_links(container, response.url)


# --------------------------------------------------
# COLLECT COMPANY EVIDENCE
# --------------------------------------------------

def evidence(status, text="", urls=()):
    return {"status": status, "text": text, "urls": list(urls)}


def collect_evidence(session, website):
    """
    Read the homepage and up to MAX_EXTRA_PAGES relevant sub-pages.

    status is one of: success, insufficient_content, request_failed,
    missing_website.
    """
    website = normalize_url(website)

    if not website:
        return evidence("missing_website")

    try:
        homepage_text, links = extract_page(session, website)
    except requests.RequestException:
        return evidence("request_failed")

    texts = [homepage_text]
    visited = [website]

    # A failing sub-page is skipped; the homepage alone may be enough.
    for url in links[:MAX_EXTRA_PAGES]:
        time.sleep(REQUEST_DELAY)

        try:
            page_text, _ = extract_page(session, url)
        except requests.RequestException:
            continue

        texts.append(page_text)
        visited.append(url)

    combined = clean_text(" ".join(texts))
    status = "success" if len(combined) >= MIN_CONTENT_LENGTH else "insufficient_content"

    return evidence(status, combined, visited)


# --------------------------------------------------
# CLASSIFY
# --------------------------------------------------

def classify(text):
    """
    Return (sector, {sector: [matched keywords]}).

    One matching sector -> that sector; several -> mixed livestock; none
    -> crop-only if the text says so explicitly, otherwise unknown.
    """
    text = text.casefold()

    matches = {}

    for sector, patterns in PATTERNS.items():
        found = [keyword for keyword, pattern in patterns if pattern.search(text)]

        if found:
            matches[sector] = found

    if len(matches) > 1:
        return MIXED_SECTOR, matches

    if matches:
        return next(iter(matches)), matches

    if any(pattern.search(text) for pattern in CROP_ONLY_PATTERNS):
        return CROP_ONLY_SECTOR, {}

    return UNKNOWN_SECTOR, {}


# --------------------------------------------------
# QUALIFICATION
# --------------------------------------------------

def qualify_companies():
    """Classify every candidate, update the database, return the report."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    report = []
    updates = []  # (sector, source_name, company, address) for the UPDATE

    with sqlite3.connect(DB_PATH) as conn:
        candidates = conn.execute(
            """
            SELECT company, address, website, sector
            FROM discovery_candidates
            WHERE source_name = ?
            ORDER BY company, address
            """,
            (SOURCE_NAME,),
        ).fetchall()

        print("Companies to qualify:", len(candidates))

        # A session reuses the TCP connection across requests to one site.
        with requests.Session() as session:
            session.headers["User-Agent"] = USER_AGENT

            for index, (company, address, website, previous_sector) in enumerate(candidates, 1):
                result = collect_evidence(session, website)

                # A missing or unreadable website is no reason to change
                # the existing classification, so only classify on success.
                if result["status"] == "success":
                    classification, found = classify(result["text"])
                else:
                    classification, found = UNKNOWN_SECTOR, {}

                # Store only explicit results; unknown keeps the old sector.
                if classification != UNKNOWN_SECTOR:
                    updates.append((classification, SOURCE_NAME, company, address))

                report.append({
                    "company": company,
                    "website": website,
                    "previous_sector": previous_sector,
                    "classification": classification,
                    "status": result["status"],
                    "evidence": str(found),
                    "evidence_urls": " | ".join(result["urls"]),
                })

                print(f"{index}/{len(candidates)} {company}: {classification}")

        # All sector changes in one call; the `with` block commits them.
        conn.executemany(
            """
            UPDATE discovery_candidates
            SET sector = ?
            WHERE source_name = ? AND company = ? AND address = ?
            """,
            updates,
        )

    return report


# --------------------------------------------------
# SAVE EVIDENCE REPORT
# --------------------------------------------------

def save_report(report):
    """Write the evidence report (utf-8-sig so Excel shows umlauts correctly)."""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with REPORT_PATH.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(report)


# --------------------------------------------------
# FINAL REPORT
# --------------------------------------------------

def print_report(report):
    """Print how many companies fell into each classification."""
    counts = Counter(item["classification"] for item in report)

    print()
    print("=" * 50)
    print("LIVESTOCK COMPANY QUALIFICATION REPORT")
    print("=" * 50)
    print("Companies checked:", len(report))
    print()

    for classification, count in counts.most_common():
        print(f"{classification}: {count}")

    print()
    print("Evidence report:", REPORT_PATH)
    print("Existing database:", DB_PATH)
    print("=" * 50)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print("=" * 50)
    print("ANIMAL FARMING GERMANY")
    print("STEP 20: LIVESTOCK COMPANY QUALIFICATION")
    print("=" * 50)

    report = qualify_companies()
    save_report(report)
    print_report(report)


if __name__ == "__main__":
    main()
