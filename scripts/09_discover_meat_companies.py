"""
STEP 09: Discover slaughtering companies.

Source: VDF (Verband der Fleischwirtschaft) members, category
"Schlachtung" (slaughtering).

The directory lists member cards; each links to a profile page with
address and contact details (parsed by common.read_company_profile).
Local village butchers are excluded.
"""

from common import (
    RAW_DIR, dedupe, make_record, member_profiles, print_banner,
    print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "vdf_meat_companies.csv"
SOURCE_URL = "https://www.v-d-f.de/mitglieder-uebersicht/mitglieder/mg-schlachtung"
SOURCE_NAME = "VDF Meat Industry Member Directory - Slaughtering"
SECTOR = "Meat Processing and Slaughtering"
DESCRIPTION = "VDF member listed in the slaughtering category."

# Small local butcher shops are not industrial employers.
EXCLUDED_TERM = "landmetzgerei"


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def collect():
    print("Opening VDF slaughtering directory...")
    records = []

    for url, profile in member_profiles(SOURCE_URL):
        if EXCLUDED_TERM in profile["company"].casefold():
            print("  Skipped: local butcher")
            continue

        records.append(make_record(
            **profile,
            sector=SECTOR,
            description=DESCRIPTION,
            source_name=SOURCE_NAME,
            source_url=url,
        ))

    return dedupe(records)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 09: MEAT COMPANY DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No German meat companies extracted.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("MEAT COMPANY DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
