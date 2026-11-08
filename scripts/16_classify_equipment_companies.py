"""
STEP 16: Classify equipment makers by livestock relevance (first pass).

The VDMA directory (step 04) lists every agricultural machinery maker,
including many that only build crop or field machinery. This step
reads each company's homepage, where robots.txt allows it, and looks
for keywords:

    direct        livestock equipment (barns, milking, feeding, manure)
    indirect      forage and feed machinery (silage, balers, mixers)
    crop_focused  at least two crop-only terms and nothing livestock-related
    unknown       no evidence; step 17 takes a deeper look

Results go to the company_relevance table. The step can be resumed:
companies already classified are skipped.
"""

import time
from collections import Counter

from common import (
    PROCESSED_DIR, RobotsRules, connect, fetch_allowed_page, find_keywords,
    new_session, normalize_url, now_utc, page_text, print_banner, save_csv,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = PROCESSED_DIR / "equipment_classification.csv"
SOURCE_NAME = "VDMA Landtechnik Member Directory"

# Plain research user agent, so site owners can address us in robots.txt.
USER_AGENT = "AnimalFarmingGermanyResearch/1.0"
REQUEST_DELAY = 1.5

COLUMNS = [
    "discovery_id", "company", "relevance", "matched_keywords",
    "evidence_url", "classification_status", "checked_at",
]

DIRECT_KEYWORDS = [
    "stalltechnik", "stalleinrichtung", "stallausrüstung", "stallbau",
    "melktechnik", "melkroboter", "melkanlage", "milking system",
    "dairy farming", "livestock equipment", "livestock housing",
    "animal housing", "feeding system", "fütterungsanlage",
    "fütterungstechnik", "automatische fütterung", "schweinehaltung",
    "rinderhaltung", "geflügelhaltung", "tierhaltung", "nutztierhaltung",
    "herdenmanagement", "entmistung", "gülletechnik",
]

INDIRECT_KEYWORDS = [
    "futterernte", "futtererntetechnik", "futteraufbereitung",
    "futterproduktion", "futtermischwagen", "silagetechnik", "silage",
    "forage harvester", "forage equipment", "feed production",
    "feed processing", "grassland equipment", "grünlandtechnik",
    "ballenpresse",
]

CROP_KEYWORDS = [
    "bodenbearbeitung", "pflanzenschutztechnik", "sätechnik", "saattechnik",
    "crop protection", "crop farming", "seed drilling", "soil cultivation",
    "ackerbau", "pflanzenbau", "mähdrescher", "combine harvester",
]

# Crop-only is a strong claim, so it needs at least this many terms.
MIN_CROP_TERMS = 2


# --------------------------------------------------
# CLASSIFY
# --------------------------------------------------

def classify(text):
    """Return (relevance, matched keywords) for a casefolded page text."""
    if direct := find_keywords(text, DIRECT_KEYWORDS):
        return "direct", direct

    if indirect := find_keywords(text, INDIRECT_KEYWORDS):
        return "indirect", indirect

    crop = find_keywords(text, CROP_KEYWORDS)
    return ("crop_focused" if len(crop) >= MIN_CROP_TERMS else "unknown"), crop


def classify_company(session, robots, website):
    """Return (relevance, keywords, evidence_url, status) for one website."""
    website = normalize_url(website)

    if not website:
        return "unknown", [], None, "missing_website"

    soup, final_url, status = fetch_allowed_page(session, robots, website)

    if soup is None:
        return "unknown", [], website, status

    relevance, keywords = classify(page_text(soup))
    return relevance, keywords, final_url, status


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 16: EQUIPMENT COMPANY CLASSIFICATION")

    counts = Counter()

    with connect() as conn, new_session(USER_AGENT) as session:
        robots = RobotsRules(session, USER_AGENT)

        companies = conn.execute(
            "SELECT id, company, website FROM discovery_candidates "
            "WHERE source_name = ? ORDER BY id",
            (SOURCE_NAME,),
        ).fetchall()

        done = {row[0] for row in conn.execute("SELECT discovery_id FROM company_relevance")}
        todo = [c for c in companies if c["id"] not in done]
        print(f"Companies: {len(companies)} | already classified: {len(companies) - len(todo)}")

        for index, company in enumerate(todo, start=1):
            print(f"\n[{index}/{len(todo)}] {company['company']}")

            relevance, keywords, evidence_url, status = classify_company(
                session, robots, company["website"]
            )
            counts[relevance] += 1

            # Commit each result, so an interrupted run can resume.
            conn.execute(
                f"""
                INSERT INTO company_relevance ({", ".join(COLUMNS)})
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (discovery_id) DO UPDATE SET
                    {", ".join(f"{c} = excluded.{c}" for c in COLUMNS[1:])}
                """,
                (company["id"], company["company"], relevance, " | ".join(keywords),
                 evidence_url, status, now_utc()),
            )
            conn.commit()

            print(f"  {relevance} ({status}) {keywords}")
            time.sleep(REQUEST_DELAY)

        rows = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM company_relevance ORDER BY company"
        ).fetchall()

    save_csv([dict(row) for row in rows], CSV_PATH, fields=COLUMNS)

    print()
    print_banner("EQUIPMENT CLASSIFICATION REPORT")
    print("Stored classifications:", len(rows))
    print("Classified in this run:")

    for relevance, total in counts.most_common():
        print(f"  {relevance}: {total}")


if __name__ == "__main__":
    main()
