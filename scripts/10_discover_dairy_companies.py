"""Step 10: collect German dairy companies from the MIV member directory."""

import re

import common
from common import (
    ROOT, dedupe, fetch_soup, now_utc, print_banner,
    save_csv, save_database,
)

CSV_PATH = ROOT / "data/raw/miv_dairy_companies.csv"
SOURCE_URL = "https://milchindustrie.de/ueber-uns/unsere-mitglieder/"
SOURCE_NAME = "MIV Milchindustrie-Verband Member Directory"
USER_AGENT = "AnimalFarmingGermanyResearch/1.0"


def get_text(card, selector):
    # Keep raw whitespace: company and address form the database upsert key.
    return common.get_text(card, selector, squash=False)


def extract_record(card):
    company = get_text(card, ".company-name")
    location = get_text(card, ".place-postcode")
    member_type = card.get("data-type", "")

    # Skip the association office and anything outside Germany.
    match = re.match(r"^(\d{5})\s+(.+)$", location)
    if not company or member_type == "Geschäftsstelle" or not match:
        return None

    street = get_text(card, ".street")
    website = card.select_one(".homepage a[href]")
    products = card.select(".categories")
    products = products[-1].get_text(" ", strip=True) if products else ""

    if member_type == "Firmensitz Förderer":
        sector = "Dairy Technology and Services"
    else:
        sector = "Dairy Processing and Manufacturing"

    return {
        "company": company,
        "sector": sector,
        "city": match.group(2).strip(),
        "postal_code": match.group(1),
        "address": ", ".join(p for p in [street, location] if p),
        "website": website["href"].strip() if website else "",
        "email": get_text(card, ".email"),
        "phone": get_text(card, ".phone"),
        "description": f"Directory type: {member_type}. Products: {products}",
        "source_name": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "collected_at": now_utc(),
    }


def collect():
    print("Opening MIV dairy directory...")
    cards = fetch_soup(SOURCE_URL, USER_AGENT).select("ul.table > li.main-li")
    print("Directory entries found:", len(cards))
    if not cards:
        raise RuntimeError(
            "No company cards found. Website structure may have changed."
        )
    return dedupe(filter(None, map(extract_record, cards)))


def report(records):
    total = len(records)
    with_websites = sum(bool(r["website"]) for r in records)

    print()
    print_banner("DAIRY DATA COLLECTION REPORT")
    print("Total German listings:", total)
    print("Unique company names:", len({r["company"].casefold() for r in records}))
    print("Companies with websites:", with_websites)
    print("Companies with cities:", sum(bool(r["city"]) for r in records))
    if total:
        print("Website coverage:", f"{with_websites / total:.1%}")
    print("=" * 45)


def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 10: DAIRY COMPANY DISCOVERY")
    records = collect()
    if not records:
        raise RuntimeError("No German dairy companies extracted.")
    save_csv(records, CSV_PATH)
    save_database(records)
    report(records)
    print("\nDairy company discovery completed.")


if __name__ == "__main__":
    main()
