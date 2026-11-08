"""
STEP 17: Classify the remaining equipment makers (second pass).

Takes the VDMA companies whose homepage loaded fine in step 16 but gave
no keyword evidence ("unknown"). For each one it reads the homepage plus
up to three internal pages whose link text or URL looks like products,
solutions or industries served, and classifies them again with
direct / indirect / crop keyword lists.

Results go to company_activity_enrichment. The step can be resumed:
companies already enriched are skipped.
"""

import time
from urllib.parse import urldefrag, urljoin, urlparse

from common import (
    PROCESSED_DIR, RobotsRules, connect, fetch_allowed_page, find_keywords,
    new_session, normalize_url, now_utc, page_text, print_banner, save_csv,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = PROCESSED_DIR / "company_activity_enrichment.csv"
SOURCE_NAME = "VDMA Landtechnik Member Directory"

# Plain research user agent, so site owners can address us in robots.txt.
USER_AGENT = "AnimalFarmingGermanyResearch/1.0"
REQUEST_DELAY = 1.5

# Internal pages read in addition to the homepage.
MAX_INTERNAL_PAGES = 3

COLUMNS = [
    "discovery_id", "company", "classification", "direct_keywords",
    "indirect_keywords", "crop_keywords", "evidence_urls",
    "pages_analyzed", "status", "enriched_at",
]

DIRECT_TERMS = [
    "stalltechnik", "stalleinrichtung", "stallausrüstung", "melktechnik",
    "melkroboter", "melkanlage", "fütterungsanlage", "fütterungstechnik",
    "herdenmanagement", "rinderhaltung", "schweinehaltung",
    "geflügelhaltung", "nutztierhaltung", "tierhaltung", "livestock farming",
    "livestock equipment", "dairy farming", "milking system",
    "animal feeding", "poultry farming", "pig farming", "barn equipment",
    "entmistung",
]

INDIRECT_TERMS = [
    "futterernte", "futtererntetechnik", "futterproduktion",
    "futteraufbereitung", "silagetechnik", "grünlandtechnik",
    "forage harvesting", "forage equipment", "feed processing",
    "feed production", "baling equipment",
]

CROP_TERMS = [
    "bodenbearbeitung", "pflanzenschutztechnik", "sätechnik", "saattechnik",
    "ackerbau", "pflanzenbau", "soil cultivation", "crop protection",
    "seed drilling", "combine harvester",
]

# Link text / URL words that suggest a page describing what the company
# makes or which industries it serves. More matches = visited first.
PAGE_TERMS = [
    "produkt", "product", "solution", "lösung", "loesung", "anwendung",
    "application", "branche", "industry", "industries", "landwirtschaft",
    "agriculture", "tierhaltung", "livestock", "dairy", "feeding", "milking",
]

SKIPPED_LINK_PREFIXES = ("#", "mailto:", "tel:", "javascript:")

MIN_CROP_TERMS = 2


# --------------------------------------------------
# LINK SELECTION
# --------------------------------------------------

def site_host(url):
    """Hostname without 'www.', so www.x.de and x.de count as one site."""
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def internal_links(soup, base_url):
    """Same-site links that look relevant, most relevant first."""
    scored, seen = [], set()

    for link in soup.find_all("a", href=True):
        href = link["href"].strip()

        if href.startswith(SKIPPED_LINK_PREFIXES):
            continue

        # Drop "#section" parts so one page is not visited twice.
        url = urldefrag(normalize_url(urljoin(base_url, href)))[0]

        if not url or url in seen or site_host(url) != site_host(base_url):
            continue

        seen.add(url)
        label = f"{link.get_text(' ', strip=True)} {url}".casefold()

        if score := sum(term in label for term in PAGE_TERMS):
            scored.append((score, url))

    # sort is stable: equally scored links keep their page order.
    scored.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in scored]


# --------------------------------------------------
# ENRICH
# --------------------------------------------------

def enrich_company(session, robots, website):
    """Read homepage + relevant sub-pages and classify the company."""
    result = {
        "classification": "unknown", "direct": set(), "indirect": set(),
        "crop": set(), "urls": [], "pages": 0, "status": "missing_website",
    }

    website = urldefrag(normalize_url(website))[0]

    if not website:
        return result

    homepage, final_url, result["status"] = fetch_allowed_page(session, robots, website)

    if homepage is None:
        return result

    pages = [(homepage, final_url)]

    for url in internal_links(homepage, final_url)[:MAX_INTERNAL_PAGES]:
        time.sleep(REQUEST_DELAY)
        soup, page_url, _ = fetch_allowed_page(session, robots, url)

        if soup is not None:
            pages.append((soup, page_url))

    for soup, url in pages:
        text = page_text(soup)
        found = {
            "direct": find_keywords(text, DIRECT_TERMS),
            "indirect": find_keywords(text, INDIRECT_TERMS),
            "crop": find_keywords(text, CROP_TERMS),
        }

        for kind, keywords in found.items():
            result[kind].update(keywords)

        # Remember which pages provided evidence.
        if any(found.values()):
            result["urls"].append(url)

        result["pages"] += 1

    if result["direct"]:
        result["classification"] = "direct"
    elif result["indirect"]:
        result["classification"] = "indirect"
    elif len(result["crop"]) >= MIN_CROP_TERMS:
        result["classification"] = "crop_focused"

    return result


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 17: EQUIPMENT COMPANY ENRICHMENT")

    with connect() as conn, new_session(USER_AGENT) as session:
        robots = RobotsRules(session, USER_AGENT)

        # Websites that loaded fine in step 16 but showed no evidence.
        companies = conn.execute(
            """
            SELECT d.id, d.company, d.website
            FROM discovery_candidates d
            JOIN company_relevance r ON d.id = r.discovery_id
            WHERE d.source_name = ?
              AND r.relevance = 'unknown'
              AND r.classification_status = 'success'
            ORDER BY d.id
            """,
            (SOURCE_NAME,),
        ).fetchall()

        done = {row[0] for row in conn.execute("SELECT discovery_id FROM company_activity_enrichment")}
        todo = [c for c in companies if c["id"] not in done]
        print(f"Eligible: {len(companies)} | already enriched: {len(companies) - len(todo)}")

        for index, company in enumerate(todo, start=1):
            print(f"\n[{index}/{len(todo)}] {company['company']}")
            result = enrich_company(session, robots, company["website"])

            # Commit each result, so an interrupted run can resume.
            conn.execute(
                f"""
                INSERT INTO company_activity_enrichment ({", ".join(COLUMNS)})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (discovery_id) DO UPDATE SET
                    {", ".join(f"{c} = excluded.{c}" for c in COLUMNS[1:])}
                """,
                (
                    company["id"], company["company"], result["classification"],
                    " | ".join(sorted(result["direct"])),
                    " | ".join(sorted(result["indirect"])),
                    " | ".join(sorted(result["crop"])),
                    " | ".join(result["urls"]), result["pages"], result["status"],
                    now_utc(),
                ),
            )
            conn.commit()

            print(f"  {result['classification']} | {result['pages']} pages | {result['status']}")
            time.sleep(REQUEST_DELAY)

        rows = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM company_activity_enrichment ORDER BY company"
        ).fetchall()

    if rows:
        save_csv([dict(row) for row in rows], CSV_PATH, fields=COLUMNS)


if __name__ == "__main__":
    main()
