"""
STEP 05: Discover cattle and pig value chain companies.

Source: BRS (Bundesverband Rind und Schwein) member directory.

The member table is built by JavaScript, so it is opened in a headless
Playwright browser, switched to show all members on one page, and then
read in one pass. BRS members include breeders, marketing companies and
associations, so the sector is a provisional "Subsector Unverified".
"""

from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from common import (
    RAW_DIR, check_count, dedupe, make_record, mailto_address,
    print_banner, print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "cattle_and_pig_companies.csv"
SOURCE_URL = "https://www.rind-schwein.de/mitglieder/de/list/"
SOURCE_NAME = "BRS Member Directory"
SECTOR = "Cattle and Pig Value Chain - Subsector Unverified"

TABLE = "#fancylist_memberlist_table"

# BRS has about 180-200 members; outside this range the parser is broken.
EXPECTED_COUNT = (170, 250)

# Runs in the browser and returns every table row as plain data in a
# single call, instead of one Playwright round trip per cell. innerText
# gives exactly the text Playwright's inner_text() would.
READ_ROWS_JS = """rows => rows.map(row => {
    const cells = Array.from(row.querySelectorAll('td'));
    const link = cells.length ? cells[0].querySelector('a') : null;
    return {
        cells: cells.length,
        name: link ? link.innerText : '',
        href: link ? link.getAttribute('href') || '' : '',
        postal_code: cells[1] ? cells[1].innerText : '',
        city: cells[2] ? cells[2].innerText : '',
        contacts: cells[3]
            ? Array.from(cells[3].querySelectorAll('a'), a => a.getAttribute('href') || '')
            : [],
    };
})"""


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def read_rows():
    """Open the directory, show all members, and return the raw rows."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            page = browser.new_page()
            print("Opening BRS directory...")
            page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.locator(TABLE).wait_for(timeout=30_000)

            # Show up to 500 members on one page instead of paging.
            page.locator('select[name="lines"]').select_option("500")
            page.wait_for_function(
                f"() => document.querySelectorAll('{TABLE} tr').length > 150",
                timeout=30_000,
            )

            rows = page.locator(f"{TABLE} tr").evaluate_all(READ_ROWS_JS)
            print("Table rows:", len(rows))
            return rows

        finally:
            browser.close()


def extract_record(row):
    """Turn one table row into a record, or None for header rows."""
    company = row["name"].strip()

    # Header rows have fewer than four cells and no member link.
    if row["cells"] < 4 or not company:
        return None

    postal_code = row["postal_code"].strip()
    city = row["city"].strip()
    website = email = ""

    for href in map(str.strip, row["contacts"]):
        if href.startswith("mailto:"):
            email = mailto_address(href)
        elif href.startswith(("http://", "https://")):
            website = href

    return make_record(
        company=company,
        sector=SECTOR,
        city=city,
        postal_code=postal_code,
        # Only postcode and city are published, no street.
        address=" ".join(part for part in (postal_code, city) if part),
        website=website,
        email=email,
        source_name=SOURCE_NAME,
        source_url=urljoin(SOURCE_URL, row["href"]),
    )


def collect():
    return dedupe(filter(None, map(extract_record, read_rows())))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 05: CATTLE AND PIG COMPANY DISCOVERY")

    records = collect()
    check_count(records, *EXPECTED_COUNT, SOURCE_NAME)

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("CATTLE AND PIG DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
