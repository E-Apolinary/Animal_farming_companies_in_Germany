"""
STEP 19: Find out which animals each livestock producer keeps.

Takes the IMA farms from step 15, reads each farm's website (homepage
plus up to two relevant sub-pages) and looks for keywords that show
which livestock it keeps: pigs, cattle, dairy, poultry or sheep/goats.

A clear result replaces the placeholder sector in discovery_candidates:
one species -> that sector, several -> "Mixed Livestock Production",
none but an explicit crop-only statement -> "Out of Scope - Crop Only".
Unclear results leave the database unchanged. Every check is written to
an evidence report CSV.
"""

import re
import time
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import (
    PROCESSED_DIR, clean, connect, new_session, normalize_url,
    print_banner, save_csv,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

REPORT_PATH = PROCESSED_DIR / "livestock_producer_qualification.csv"
SOURCE_NAME = "IMA Livestock Production Directory"

UNKNOWN_SECTOR = "Livestock Farming - Relevance Unverified"
MIXED_SECTOR = "Mixed Livestock Production"
CROP_ONLY_SECTOR = "Out of Scope - Crop Only"

MAX_EXTRA_PAGES = 2       # sub-pages per website besides the homepage
REQUEST_DELAY = 0.3       # pause before each sub-page request
TIMEOUT = 20
MIN_CONTENT_LENGTH = 100  # less text than this is too little to judge

REPORT_FIELDS = [
    "company", "website", "previous_sector", "classification", "status",
    "evidence", "evidence_urls",
]

# Menus, footers and scripts mention all sorts of keywords that say
# nothing about what the farm actually does.
NOISE_SELECTOR = "script, style, nav, footer, header, noscript, form, aside"
HTML_TYPES = ("text/html", "application/xhtml+xml")


# --------------------------------------------------
# CLASSIFICATION RULES
# --------------------------------------------------

# Keywords (German and English) that show a livestock activity.
KEYWORDS = {
    "Pig Production": [
        "schweinemast", "ferkelerzeugung", "ferkelproduktion", "sauenhaltung",
        "schweinezucht", "schweinehaltung", "pig farming", "pig production",
        "sow farming",
    ],
    "Cattle Production": [
        "rindermast", "bullenmast", "rinderhaltung", "mutterkuhhaltung",
        "rinderaufzucht", "rinderzucht", "beef cattle", "cattle farming",
        "cattle breeding",
    ],
    "Dairy Farming": [
        "milchviehhaltung", "milchproduktion", "milcherzeugung",
        "milchviehbetrieb", "milchkuhhaltung", "dairy farming", "dairy herd",
        "milk production",
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
PATTERNS = {
    sector: [(kw, re.compile(rf"\b{kw}\b", re.IGNORECASE)) for kw in keywords]
    for sector, keywords in KEYWORDS.items()
}

# Must state explicitly that crop farming is the ONLY activity.
# NOTE: classify() casefolds the text, which turns "ß" into "ss", so the
# two patterns containing "ß" can never match. Kept as-is to preserve
# the published results; see README "Known limitations".
CROP_ONLY_PATTERNS = [
    re.compile(p) for p in (
        r"\bausschließlich(?:er|e|es)?\s+ackerbau\b",
        r"\breiner\s+ackerbaubetrieb\b",
        r"\bspezialisiert\s+ausschließlich\s+auf\s+ackerbau\b",
        r"\bexclusively\s+crop\s+farming\b",
        r"\bcrop[- ]only\s+farm\b",
    )
]

# Link text or URL path words that suggest a page about the farm's work.
RELEVANT_LINK_TERMS = (
    "tierhaltung", "tierproduktion", "landwirtschaft", "betrieb",
    "produktion", "schweine", "rinder", "milchvieh", "gefluegel",
    "geflügel", "ueber-uns", "über-uns", "about", "farming", "livestock",
    "production",
)


# --------------------------------------------------
# WEBSITE READING
# --------------------------------------------------

def relevant_links(container, page_url):
    """Same-site links whose text or path looks relevant, in page order."""
    base_host = (urlparse(page_url).hostname or "").lower()
    links = []

    for link in container.select("a[href]"):
        href = link["href"].strip()

        if not href:
            continue

        target = urljoin(page_url, href)
        parsed = urlparse(target)

        if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() != base_host:
            continue

        label = f"{link.get_text(' ', strip=True)} {parsed.path}".casefold()

        if any(term in label for term in RELEVANT_LINK_TERMS):
            links.append(target)

    return list(dict.fromkeys(links))  # drop duplicates, keep order


def read_page(session, url):
    """(main text, relevant same-site links); ('', []) for non-HTML pages."""
    response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()

    if not any(kind in response.headers.get("Content-Type", "").lower() for kind in HTML_TYPES):
        return "", []

    soup = BeautifulSoup(response.text, "html.parser")

    for element in soup.select(NOISE_SELECTOR):
        element.decompose()

    container = soup.find("main") or soup.body

    if container is None:
        return "", []

    # response.url is the address after redirects, the real host.
    return clean(container.get_text(" ", strip=True)), relevant_links(container, response.url)


def collect_evidence(session, website):
    """
    Combined text of homepage + up to MAX_EXTRA_PAGES sub-pages.

    status: success | insufficient_content | request_failed | missing_website
    """
    website = normalize_url(website)

    if not website:
        return {"status": "missing_website", "text": "", "urls": []}

    try:
        homepage_text, links = read_page(session, website)
    except requests.RequestException:
        return {"status": "request_failed", "text": "", "urls": []}

    texts, visited = [homepage_text], [website]

    # A failing sub-page is skipped; the homepage alone may be enough.
    for url in links[:MAX_EXTRA_PAGES]:
        time.sleep(REQUEST_DELAY)

        try:
            texts.append(read_page(session, url)[0])
            visited.append(url)
        except requests.RequestException:
            continue

    text = clean(" ".join(texts))
    status = "success" if len(text) >= MIN_CONTENT_LENGTH else "insufficient_content"
    return {"status": status, "text": text, "urls": visited}


# --------------------------------------------------
# CLASSIFY
# --------------------------------------------------

def classify(text):
    """Return (sector, {sector: [matched keywords]})."""
    text = text.casefold()
    matches = {}

    for sector, patterns in PATTERNS.items():
        if found := [kw for kw, pattern in patterns if pattern.search(text)]:
            matches[sector] = found

    if len(matches) > 1:
        return MIXED_SECTOR, matches
    if matches:
        return next(iter(matches)), matches
    if any(pattern.search(text) for pattern in CROP_ONLY_PATTERNS):
        return CROP_ONLY_SECTOR, {}

    return UNKNOWN_SECTOR, {}


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def qualify(conn, session):
    """Classify every IMA farm; return (report rows, sector updates)."""
    farms = conn.execute(
        "SELECT company, address, website, sector FROM discovery_candidates "
        "WHERE source_name = ? ORDER BY company, address",
        (SOURCE_NAME,),
    ).fetchall()

    print("Companies to qualify:", len(farms))
    report, updates = [], []

    for index, (company, address, website, previous_sector) in enumerate(farms, 1):
        evidence = collect_evidence(session, website)

        # An unreadable website is no reason to change the sector.
        if evidence["status"] == "success":
            sector, found = classify(evidence["text"])
        else:
            sector, found = UNKNOWN_SECTOR, {}

        if sector != UNKNOWN_SECTOR:
            updates.append((sector, SOURCE_NAME, company, address))

        report.append({
            "company": company,
            "website": website,
            "previous_sector": previous_sector,
            "classification": sector,
            "status": evidence["status"],
            "evidence": str(found),
            "evidence_urls": " | ".join(evidence["urls"]),
        })

        print(f"{index}/{len(farms)} {company}: {sector}")

    return report, updates


def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 19: LIVESTOCK PRODUCER QUALIFICATION")

    with connect() as conn, new_session() as session:
        report, updates = qualify(conn, session)

        # All sector changes in one call; the `with` block commits them.
        conn.executemany(
            "UPDATE discovery_candidates SET sector = ? "
            "WHERE source_name = ? AND company = ? AND address = ?",
            updates,
        )

    save_csv(report, REPORT_PATH, fields=REPORT_FIELDS)

    print()
    print_banner("LIVESTOCK QUALIFICATION REPORT")
    print("Companies checked:", len(report))

    for sector, total in Counter(r["classification"] for r in report).most_common():
        print(f"  {sector}: {total}")

    print("Database updated:", len(updates), "sectors")


if __name__ == "__main__":
    main()
