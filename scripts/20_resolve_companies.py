"""
STEP 20: Resolve companies across sources (entity resolution).

The same company often appears in several directories, e.g. a dairy
listed by both MIV and Export-Union. This step merges the staging rows
in discovery_candidates into one row per real company:

    resolved_companies        one row per company (stable hashed ID)
    resolved_company_sectors  every sector the company was listed under
    resolved_company_sources  which staging rows were merged into it

Companies are matched on a normalised name (case, accents, punctuation
and spacing ignored). Companies sharing a website domain are reported
for manual review, because they may be related (subsidiaries, brands).

The final dataset is exported to data/processed/resolved_companies.csv.
"""

import hashlib
import re
import unicodedata
from collections import defaultdict
from urllib.parse import urlparse

from common import PROCESSED_DIR, connect, normalize_url, print_banner, save_csv


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CSV_PATH = PROCESSED_DIR / "resolved_companies.csv"

EXPORT_FIELDS = ["company_id", "company_name", "city", "website", "sectors", "sources"]


# --------------------------------------------------
# NORMALISATION
# --------------------------------------------------

def normalize_name(name):
    """
    Matching key for a company name.

    "Müller GmbH & Co. KG" and "MÜLLER GmbH & Co KG" both become
    "müller gmbh co kg": NFKC unifies look-alike characters, casefold
    ignores case, and punctuation and repeated spaces are removed.
    """
    name = unicodedata.normalize("NFKC", str(name or "")).casefold()
    name = re.sub(r"[^\w\s]", " ", name)
    return " ".join(name.split())


def company_id(normalized_name):
    """Stable ID: the same name always gets the same ID across runs."""
    return "COMP_" + hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()[:20]


def website_domain(website):
    """'https://www.x.de/path' -> 'x.de', or None."""
    host = urlparse(normalize_url(website)).hostname
    return host.lower().removeprefix("www.") if host else None


# --------------------------------------------------
# RESOLVE
# --------------------------------------------------

def resolve(conn):
    """Merge all staging rows; return (rows processed, rows skipped)."""
    rows = conn.execute(
        "SELECT id, company, sector, city, website, source_name "
        "FROM discovery_candidates ORDER BY id"
    ).fetchall()

    if not rows:
        raise RuntimeError("No discovery candidates found.")

    companies, sectors, sources = [], [], []

    for row in rows:
        normalized = normalize_name(row["company"])

        if not normalized:
            continue

        cid = company_id(normalized)
        companies.append((cid, row["company"], normalized, row["website"], row["city"]))
        sources.append((cid, row["id"], row["source_name"]))

        if row["sector"]:
            sectors.append((cid, row["sector"]))

    # The first row seen names the company. Later rows only fill a
    # website or city that is still empty; they never overwrite one.
    conn.executemany(
        """
        INSERT INTO resolved_companies (company_id, company_name, normalized_name, website, city)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (company_id) DO UPDATE SET
            website = CASE WHEN TRIM(COALESCE(resolved_companies.website, '')) = ''
                           THEN excluded.website ELSE resolved_companies.website END,
            city    = CASE WHEN TRIM(COALESCE(resolved_companies.city, '')) = ''
                           THEN excluded.city ELSE resolved_companies.city END
        """,
        companies,
    )

    conn.executemany(
        "INSERT OR IGNORE INTO resolved_company_sectors (company_id, sector) VALUES (?, ?)",
        sectors,
    )

    # Lineage: every staging row points to the company it was merged into.
    conn.executemany(
        """
        INSERT INTO resolved_company_sources (company_id, discovery_id, source_name)
        VALUES (?, ?, ?)
        ON CONFLICT (discovery_id) DO UPDATE SET
            company_id = excluded.company_id,
            source_name = excluded.source_name
        """,
        sources,
    )

    return len(companies), len(rows) - len(companies)


# --------------------------------------------------
# REPORTS
# --------------------------------------------------

def report_shared_domains(conn):
    """Print companies that share a website domain (possibly related)."""
    by_domain = defaultdict(list)

    for row in conn.execute("SELECT company_name, website FROM resolved_companies"):
        if domain := website_domain(row["website"]):
            by_domain[domain].append(row["company_name"])

    shared = {domain: names for domain, names in by_domain.items() if len(names) > 1}

    print("\nCompanies sharing a website domain (review manually):")

    if not shared:
        print("  none")

    for domain, names in sorted(shared.items()):
        print(f"\n  {domain}")

        for name in names:
            print("   -", name)


def export_companies(conn):
    """Write the resolved company list, one row per company."""
    rows = conn.execute(
        """
        SELECT c.company_id, c.company_name, c.city, c.website,
               (SELECT GROUP_CONCAT(sector, ' | ') FROM resolved_company_sectors s
                 WHERE s.company_id = c.company_id) AS sectors,
               (SELECT GROUP_CONCAT(source_name, ' | ') FROM (
                    SELECT DISTINCT source_name FROM resolved_company_sources r
                     WHERE r.company_id = c.company_id)) AS sources
        FROM resolved_companies c
        ORDER BY c.company_name
        """
    ).fetchall()

    save_csv([dict(row) for row in rows], CSV_PATH, fields=EXPORT_FIELDS)


def print_summary(conn):
    def count(sql):
        return conn.execute(sql).fetchone()[0]

    print()
    print_banner("COMPANY RESOLUTION REPORT")
    print("Resolved companies:   ", count("SELECT COUNT(*) FROM resolved_companies"))
    print("Distinct sectors:     ", count("SELECT COUNT(DISTINCT sector) FROM resolved_company_sectors"))
    print("Company-sector links: ", count("SELECT COUNT(*) FROM resolved_company_sectors"))
    print("Linked source records:", count("SELECT COUNT(*) FROM resolved_company_sources"))
    print("Listed by 2+ sources: ", count(
        "SELECT COUNT(*) FROM (SELECT company_id FROM resolved_company_sources "
        "GROUP BY company_id HAVING COUNT(DISTINCT source_name) > 1)"
    ))


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 20: COMPANY RESOLUTION")

    with connect() as conn:
        processed, skipped = resolve(conn)
        print("Records processed:", processed)
        print("Records skipped:  ", skipped)

        print_summary(conn)
        report_shared_domains(conn)
        export_companies(conn)


if __name__ == "__main__":
    main()
