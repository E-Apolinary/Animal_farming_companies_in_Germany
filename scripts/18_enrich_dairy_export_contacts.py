"""
STEP 18: Fill in missing contact details for dairy exporters.

The Export-Union list (step 08) has no website, email or phone. Each
company's Export-Union profile page does, so this step visits the
profiles of companies that still lack contact data and fills only the
fields that are empty. Companies already covered by the MIV directory
(step 07), which has full contact data, are skipped.
"""

import time

import requests

from common import connect, fetch_soup, mailto_address, new_session, print_banner


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

EXPORT_SOURCE = "Export-Union Dairy Member Directory"
MIV_SOURCE = "MIV Milchindustrie-Verband Member Directory"
CONTACT_FIELDS = ["website", "email", "phone"]
REQUEST_DELAY = 0.5


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_candidates(conn):
    """Export-Union profiles missing contact data and not listed by MIV."""
    return conn.execute(
        """
        SELECT DISTINCT e.company, e.source_url
        FROM discovery_candidates e
        WHERE e.source_name = ?
          AND e.source_url LIKE 'https://www.export-union.de/%'
          AND NOT EXISTS (
              SELECT 1 FROM discovery_candidates m
              WHERE m.source_name = ?
                AND LOWER(TRIM(m.company)) = LOWER(TRIM(e.company))
          )
          AND (
              COALESCE(TRIM(e.website), '') = ''
              OR COALESCE(TRIM(e.email), '') = ''
              OR COALESCE(TRIM(e.phone), '') = ''
          )
        ORDER BY e.company, e.source_url
        """,
        (EXPORT_SOURCE, MIV_SOURCE),
    ).fetchall()


def update_company(conn, company, source_url, details):
    """Fill only the contact fields that are still empty."""
    assignments = ", ".join(
        f"{f} = CASE WHEN TRIM(COALESCE({f}, '')) = '' THEN ? ELSE {f} END"
        for f in CONTACT_FIELDS
    )
    conn.execute(
        f"""
        UPDATE discovery_candidates SET {assignments}
        WHERE source_name = ? AND company = ? AND source_url = ?
        """,
        (*(details[f] for f in CONTACT_FIELDS), EXPORT_SOURCE, company, source_url),
    )


# --------------------------------------------------
# EXTRACT
# --------------------------------------------------

def extract_contacts(session, url):
    """Website, email and phone from one Export-Union profile page."""
    soup = fetch_soup(url, session, timeout=40)
    website = soup.select_one(".web-info a[href^='http']")
    email = soup.select_one(".web-info a[href^='mailto:']")
    phone = soup.select_one(".phone-info")

    return {
        "website": website["href"].strip() if website else "",
        "email": mailto_address(email["href"]) if email else "",
        "phone": phone.get_text(" ", strip=True) if phone else "",
    }


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 18: DAIRY EXPORT CONTACT ENRICHMENT")

    found = dict.fromkeys(CONTACT_FIELDS, 0)
    enriched = failed = 0

    with connect() as conn, new_session() as session:
        candidates = get_candidates(conn)
        print("Company profiles to inspect:", len(candidates))

        for index, (company, url) in enumerate(candidates, start=1):
            print(f"[{index}/{len(candidates)}] {company}")

            try:
                details = extract_contacts(session, url)
            except requests.RequestException as error:
                failed += 1
                print("  Request failed:", error)
                continue
            finally:
                time.sleep(REQUEST_DELAY)

            if not any(details.values()):
                print("  No contact details found.")
                continue

            # Commit each profile, so an interrupted run keeps its progress.
            update_company(conn, company, url, details)
            conn.commit()
            enriched += 1

            for field in CONTACT_FIELDS:
                found[field] += bool(details[field])

            print("  Website:", details["website"] or "-")

    print()
    print_banner("DAIRY EXPORT ENRICHMENT REPORT")
    print("Profiles enriched:", enriched)

    for field, total in found.items():
        print(f"{field.capitalize()}s found:", total)

    print("Request failures:", failed)


if __name__ == "__main__":
    main()
