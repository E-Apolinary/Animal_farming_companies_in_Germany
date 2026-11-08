"""
STEP 04: Discover agricultural machinery and livestock equipment makers.

Source: VDMA Landtechnik (agricultural machinery association) members.

The directory is rendered by JavaScript and paginated, so it is read
with a headless Playwright browser. Many VDMA members build crop or
field machinery, so their sector stays "Relevance Unverified" until
steps 16 and 17 check their websites.
"""

import re

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from common import (
    POSTCODE_CITY_RE, RAW_DIR, company_address_key, make_record,
    mailto_address, print_banner, print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "vdma_landtechnik_companies.csv"
SOURCE_URL = "https://www.vdma.eu/de/mitglieder-landtechnik"
SOURCE_NAME = "VDMA Landtechnik Member Directory"
SECTOR = "Agricultural Machinery - Relevance Unverified"

# Cookie banner buttons, most privacy-friendly first.
COOKIE_BUTTONS = (
    "Nur notwendige Cookies", "Nur notwendige", "Alle ablehnen",
    "Ablehnen", "Reject All", "Deny All",
)

CARD = ".association-member"
TITLE = ".association-member__title"
NEXT_BUTTON = ".vdma-pagination-right"

# Runs in the browser: true once the list of company names differs from
# the previous page, i.e. the next page has actually loaded.
PAGE_CHANGED_JS = """previous => {
    const names = Array.from(
        document.querySelectorAll('.association-member__title')
    ).map(element => element.textContent.trim());
    return names.length > 0 && names.join('|') !== previous;
}"""


# --------------------------------------------------
# BROWSER HELPERS
# --------------------------------------------------

def handle_cookie_consent(page, wait_ms=0):
    """
    Click "only necessary cookies" (or similar) if a banner is shown.

    The banner loads a few seconds after the page and then covers the
    pagination buttons, so the first call waits up to wait_ms for it.
    """
    pattern = re.compile("^(" + "|".join(map(re.escape, COOKIE_BUTTONS)) + ")$")
    button = page.get_by_role("button", name=pattern).first

    try:
        if wait_ms:
            button.wait_for(timeout=wait_ms)

        if button.count():
            text = button.inner_text()
            button.click(timeout=3000)
            print("Cookie dialog handled:", text)
    except PlaywrightTimeout:
        pass  # no banner shown


def page_signature(page):
    """All company names on the current page, used to detect page changes."""
    return "|".join(name.strip() for name in page.locator(TITLE).all_inner_texts())


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def extract_card(card):
    """Turn one member card into a record, or None if not in Germany."""
    name = card.locator(TITLE).inner_text().strip()
    lines = [
        line.strip()
        for line in card.locator(".association-member__info-address li").all_inner_texts()
        if line.strip()
    ]

    # The last address line is the country.
    if not name or not lines or lines[-1].casefold() != "deutschland":
        return None

    postal_code, city = next(
        ((m.group(1), m.group(2).strip()) for line in lines if (m := POSTCODE_CITY_RE.match(line))),
        ("", ""),
    )

    contacts = {"website": "", "email": "", "phone": ""}

    for href in card.locator(".association-member__info-contacts a").evaluate_all(
        "links => links.map(link => link.getAttribute('href') || '')"
    ):
        href = href.strip()

        if href.startswith("mailto:"):
            contacts["email"] = mailto_address(href)
        elif href.startswith("tel:"):
            contacts["phone"] = href.removeprefix("tel:")
        elif href.startswith(("http://", "https://")):
            contacts["website"] = href

    return make_record(
        company=name,
        sector=SECTOR,
        city=city,
        postal_code=postal_code,
        address=" | ".join(lines[:-1]),
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
        **contacts,
    )


def collect():
    """Walk every directory page and return unique German members."""
    records, seen_companies, seen_pages = [], set(), set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            page = browser.new_page()
            print("Opening VDMA directory...")
            page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.locator(CARD).first.wait_for(timeout=30_000)
            handle_cookie_consent(page, wait_ms=10_000)

            total_pages = int(page.locator(".vdma-pagination").get_attribute("data-total-pages"))
            print("Directory pages:", total_pages)

            for page_number in range(1, total_pages + 1):
                page.locator(CARD).first.wait_for(timeout=30_000)

                # Seeing the same company list twice means pagination broke.
                signature = page_signature(page)

                if signature in seen_pages:
                    raise RuntimeError(
                        f"Repeated company list on page {page_number}. "
                        f"Checkpoint saved at {CSV_PATH}."
                    )

                seen_pages.add(signature)

                cards = page.locator(CARD)
                extracted = [r for r in map(extract_card, cards.all()) if r]

                for record in extracted:
                    if company_address_key(record) not in seen_companies:
                        seen_companies.add(company_address_key(record))
                        records.append(record)

                # Checkpoint after every page; the database is only
                # updated once all pages are collected.
                save_csv(records, CSV_PATH)
                print(
                    f"Page {page_number}/{total_pages}: {len(extracted)} German entries "
                    f"| {len(records)} unique"
                )

                if page_number == total_pages:
                    break

                handle_cookie_consent(page)
                page.locator(NEXT_BUTTON).click(timeout=15_000)

                try:
                    page.wait_for_function(PAGE_CHANGED_JS, arg=signature, timeout=30_000)
                except PlaywrightTimeout:
                    raise RuntimeError(
                        f"Pagination failed after page {page_number}. "
                        f"Checkpoint saved at {CSV_PATH}; database not updated."
                    ) from None

        finally:
            browser.close()

    return records


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 04: EQUIPMENT COMPANY DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No German VDMA companies extracted.")

    save_database(records)
    print_summary("EQUIPMENT COMPANY DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
