"""
STEP 10: Discover meat product manufacturers.

Source: BVWS (Bundesverband der Wurst- und Schinkenproduzenten), the
German sausage and ham producers' association.

Uses the same website system as the VDF directory (step 09), so the
shared common.member_profiles parser reads it.
"""

from common import (
    RAW_DIR, dedupe, make_record, member_profiles, print_banner,
    print_summary, save_csv, save_database,
)


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = RAW_DIR / "meat_processing_companies.csv"
SOURCE_URL = "https://www.wurstproduzenten.de/verband/alle-mitglieder"
SOURCE_NAME = "BVWS Meat Processing Member Directory"
SECTOR = "Meat Processing and Manufacturing"
DESCRIPTION = "BVWS member company involved in meat product manufacturing."


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def collect():
    print("Opening BVWS member directory...")

    return dedupe(
        make_record(
            **profile,
            sector=SECTOR,
            description=DESCRIPTION,
            source_name=SOURCE_NAME,
            source_url=url,
        )
        for url, profile in member_profiles(SOURCE_URL)
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 10: MEAT PROCESSING DISCOVERY")

    records = collect()

    if not records:
        raise RuntimeError("No German meat-processing companies extracted.")

    save_csv(records, CSV_PATH)
    save_database(records)
    print_summary("MEAT PROCESSING DISCOVERY REPORT", records)


if __name__ == "__main__":
    main()
