"""Step 12: fill missing contact details from Export-Union company profiles."""

import time

import requests

from common import USER_AGENT, connect, fetch_soup, print_banner

EXPORT_SOURCE = "Export-Union Dairy Member Directory"
MIV_SOURCE = "MIV Milchindustrie-Verband Member Directory"
REQUEST_DELAY = 0.5
CONTACT_FIELDS = ["website", "email", "phone"]


def get_candidates(conn):
    """Export-Union entries missing contact data and not already listed by MIV."""
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


def extract_profile(session, url):
    soup = fetch_soup(url, session=session, timeout=40)
    website = soup.select_one(".web-info a[href^='http']")
    email = soup.select_one(".web-info a[href^='mailto:']")
    phone = soup.select_one(".phone-info")

    website = website["href"].strip() if website else ""
    if not website.startswith(("http://", "https://")):
        website = ""

    return {
        "website": website,
        "email": (
            email["href"].removeprefix("mailto:").split("?")[0].strip()
            if email else ""
        ),
        "phone": phone.get_text(" ", strip=True) if phone else "",
    }


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


def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 12: DAIRY COMPANY ENRICHMENT")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    found = dict.fromkeys(CONTACT_FIELDS, 0)
    processed = failed = 0

    with connect() as conn:
        candidates = get_candidates(conn)
        print("Company profiles to inspect:", len(candidates))

        for index, (company, url) in enumerate(candidates, start=1):
            print(f"[{index}/{len(candidates)}] {company}")
            try:
                details = extract_profile(session, url)
            except requests.RequestException as error:
                failed += 1
                print("  Request failed:", error)
            else:
                if any(details.values()):
                    update_company(conn, company, url, details)
                    conn.commit()
                    processed += 1
                    for field in CONTACT_FIELDS:
                        found[field] += bool(details[field])
                    print("  Website:", details["website"] or "-")
                else:
                    print("  No contact details found.")
            time.sleep(REQUEST_DELAY)

    print()
    print_banner("DAIRY ENRICHMENT REPORT")
    print("Profiles enriched:", processed)
    print("Websites found:", found["website"])
    print("Emails found:", found["email"])
    print("Phones found:", found["phone"])
    print("Request failures:", failed)
    print("=" * 45)
    print("Database updated successfully.")


if __name__ == "__main__":
    main()
