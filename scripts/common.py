"""
Shared helpers for every pipeline step.

Each step script only describes its own source: where the directory
lives and how to read it. Everything they have in common is here:
paths, the record format, polite HTTP requests, robots.txt checks,
keyword matching, and saving to CSV and SQLite.
"""

import csv
import re
import sqlite3
import time
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


# --------------------------------------------------
# PATHS
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
RAW_DIR = ROOT / "data/raw"
PROCESSED_DIR = ROOT / "data/processed"
SCHEMA_PATH = ROOT / "sql/schema.sql"


# --------------------------------------------------
# RECORD FORMAT
# --------------------------------------------------

# Columns of discovery_candidates, in CSV and INSERT order.
FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]

# Unique key of discovery_candidates (used in ON CONFLICT).
KEY_FIELDS = ("source_name", "company", "address")


def now_utc():
    """Current time as an ISO 8601 string in UTC."""
    return datetime.now(timezone.utc).isoformat()


# One timestamp per run: every record a step collects shares it.
RUN_STARTED = now_utc()


def make_record(**values):
    """
    Build a discovery record with every column present.

    Columns not given are left empty; collected_at defaults to the start
    of this run. Unknown column names raise an error, so a typo cannot
    silently drop data.
    """
    unknown = set(values) - set(FIELDS)

    if unknown:
        raise KeyError(f"Unknown record fields: {sorted(unknown)}")

    record = {field: values.get(field) or "" for field in FIELDS}
    record["collected_at"] = record["collected_at"] or RUN_STARTED
    return record


# --------------------------------------------------
# TEXT HELPERS
# --------------------------------------------------

# A German location line: five-digit postcode followed by the city.
POSTCODE_CITY_RE = re.compile(r"^(\d{5})\s+(.+)$")
POSTCODE_RE = re.compile(r"\d{5}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
DOMAIN_RE = re.compile(r"^[^\s@]+\.[a-zA-Z]{2,}")


def clean(value):
    """Collapse all whitespace to single spaces; None becomes ''."""
    return " ".join(str(value or "").split())


def get_text(element, selector, squash=True):
    """Text of the first element matching selector, or ''."""
    found = element.select_one(selector)

    if found is None:
        return ""

    text = found.get_text(" ", strip=True)
    return clean(text) if squash else text


def link_href(element, selector):
    """href of the first link matching selector, or ''."""
    link = element.select_one(selector)
    return link.get("href", "").strip() if link else ""


def mailto_address(href):
    """'mailto:info@x.de?subject=Hi' -> 'info@x.de'."""
    return href.strip().removeprefix("mailto:").split("?")[0].strip()


def normalize_url(url):
    """Add https:// to a bare domain; empty input stays ''."""
    url = (url or "").strip()

    if not url or url.startswith(("http://", "https://")):
        return url

    return "https://" + url


def normalize_website(value):
    """
    Turn website text into a full URL, or '' if it is not a domain.

    Accepts 'https://x.de', '//x.de', 'www.x.de' and 'x.de'.
    """
    value = clean(value)

    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("www.") or DOMAIN_RE.match(value):
        return "https://" + value

    return ""


@cache
def _keyword_pattern(keyword):
    # Whole-word match that also works for phrases and umlauts:
    # no letter or digit may touch the keyword on either side.
    return re.compile(r"(?<!\w)" + re.escape(keyword.casefold()) + r"(?!\w)")


def find_keywords(text, keywords):
    """Keywords that appear as whole words in text (already casefolded)."""
    return [kw for kw in keywords if _keyword_pattern(kw).search(text)]


def page_text(soup, limit=150_000):
    """Visible page text, casefolded and capped at limit characters."""
    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    return clean(soup.get_text(" ", strip=True)).casefold()[:limit]


# --------------------------------------------------
# HTTP
# --------------------------------------------------

USER_AGENT = "Mozilla/5.0 (compatible; AnimalFarmingGermanyResearch/1.0)"


def new_session(user_agent=USER_AGENT):
    """A requests session that reuses connections and sends our UA."""
    session = requests.Session()
    session.headers["User-Agent"] = user_agent
    return session


def fetch_soup(url, session=None, timeout=45, retries=3, params=None):
    """
    Download a page and return it parsed as HTML.

    Failed requests are retried with a growing pause (3 s, 6 s, ...);
    the last failure is raised to the caller.
    """
    session = session or new_session()

    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            break
        except requests.RequestException as error:
            if attempt == retries:
                raise
            print(f"  Attempt {attempt} failed: {error}")
            time.sleep(attempt * 3)

    # Raw bytes let BeautifulSoup read the page's own charset declaration,
    # so umlauts survive even when the server's header is missing.
    return BeautifulSoup(response.content, "html.parser")


class RobotsRules:
    """
    Answers "may we fetch this URL?" from each site's robots.txt.

    Each site's robots.txt is downloaded once and cached. A missing file
    (404) allows everything; any other failure is treated as "no", so
    the pipeline errs on the side of not crawling.
    """

    def __init__(self, session, user_agent=USER_AGENT, timeout=15):
        self.session = session
        self.user_agent = user_agent
        self.timeout = timeout
        self._rules = {}  # origin -> True | False | RobotFileParser

    def allowed(self, url):
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        if origin not in self._rules:
            self._rules[origin] = self._load(origin)

        rule = self._rules[origin]
        return rule if isinstance(rule, bool) else rule.can_fetch(self.user_agent, url)

    def _load(self, origin):
        try:
            response = self.session.get(origin + "/robots.txt", timeout=self.timeout)
        except requests.RequestException:
            return False

        if response.status_code == 404:
            return True
        if response.status_code != 200:
            return False

        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser


def fetch_allowed_page(session, robots, url, timeout=15, max_redirects=5):
    """
    Download an HTML page only where robots.txt allows it.

    Redirects are followed by hand so that every hop is checked against
    robots.txt too. Returns (soup, final_url, status); soup and
    final_url are None unless status is "success".
    """
    try:
        for _ in range(max_redirects + 1):
            if not robots.allowed(url):
                return None, None, "robots_unavailable_or_disallowed"

            response = session.get(url, timeout=timeout, allow_redirects=False)

            if not response.is_redirect:
                break

            location = response.headers.get("Location")

            if not location:
                return None, None, "invalid_redirect"

            url = urljoin(response.url, location)
        else:
            return None, None, "too_many_redirects"

        response.raise_for_status()

    except requests.RequestException:
        return None, None, "request_failed"

    if "text/html" not in response.headers.get("Content-Type", "").lower():
        return None, None, "not_html"

    return BeautifulSoup(response.text, "html.parser"), response.url, "success"


# --------------------------------------------------
# SHARED DIRECTORY LAYOUT (VDF and BVWS)
# --------------------------------------------------

# Profile lines that are neither street nor useful contact data.
_IGNORED_PROFILE_PREFIXES = ("Telefax:", "E-Mail:", "Internet:")


def read_company_profile(soup):
    """
    Parse a company profile page of the VDF / BVWS directories.

    Both associations use the same website system: a profile is an
    .article.unternehmen block whose top-level <div>s each hold one
    address or contact line. Returns None when there is no company name
    or no German postcode.
    """
    article = soup.select_one(".article.unternehmen")
    heading = article.select_one("h1") if article else None

    if heading is None:
        return None

    street = location = phone = email = website = ""

    # The prefix of each line tells which field it is.
    for element in article.find_all("div", recursive=False):
        value = clean(element.get_text(" ", strip=True))

        if not value:
            continue
        if POSTCODE_CITY_RE.match(value):
            location = value
        elif value.startswith("Telefon:"):
            phone = clean(value.removeprefix("Telefon:"))
        elif value.startswith("Kontakt:"):
            email = mailto_address(link_href(element, "a[href^='mailto:']"))
        elif value.startswith("Webseite:"):
            website = link_href(element, "a[href^='http']")
        elif not street and not value.startswith(_IGNORED_PROFILE_PREFIXES):
            # The first unlabelled line is the street.
            street = value

    match = POSTCODE_CITY_RE.match(location)

    if not match:
        return None

    return {
        "company": clean(heading.get_text(" ", strip=True)),
        "city": clean(match.group(2)),
        "postal_code": match.group(1),
        "address": ", ".join(part for part in (street, location) if part),
        "website": website,
        "email": email,
        "phone": phone,
    }


def member_profiles(directory_url, delay=0.5):
    """
    Yield (profile_url, profile) for every member of a VDF / BVWS directory.

    The directory page lists .item-wrapper cards linking to profile
    pages; each profile is fetched with a short pause in between.
    Failed or incomplete profiles are reported and skipped.
    """
    session = new_session()
    cards = fetch_soup(directory_url, session).select(".item-wrapper")
    print("Directory entries found:", len(cards))

    if not cards:
        raise RuntimeError(f"No member cards found on {directory_url}.")

    for index, card in enumerate(cards, start=1):
        name = card.select_one(".item-titel")
        link = card.select_one("a.more[href]")

        if not name or not link:
            continue

        url = urljoin(directory_url, link["href"])
        print(f"[{index}/{len(cards)}] {clean(name.get_text(' ', strip=True))}")

        try:
            profile = read_company_profile(fetch_soup(url, session))
        except requests.RequestException as error:
            print("  Request failed:", error)
            continue
        finally:
            time.sleep(delay)

        if profile is None:
            print("  Skipped: incomplete profile")
            continue

        yield url, profile


# --------------------------------------------------
# VALIDATION
# --------------------------------------------------

def company_address_key(record):
    return record["company"].casefold(), record["address"].casefold()


def dedupe(records, key=company_address_key):
    """Keep the first record for each key, in the original order."""
    seen = set()
    unique = []

    for record in records:
        value = key(record)

        if value not in seen:
            seen.add(value)
            unique.append(record)

    return unique


def check_count(records, low, high, source):
    """
    Stop the run when a source returns an implausible number of records.

    A sudden drop or jump usually means the website layout changed and
    the parser is reading the wrong elements, so nothing is saved.
    """
    if not low <= len(records) <= high:
        raise RuntimeError(
            f"{source}: expected {low}-{high} records, got {len(records)}. "
            "Review the website structure before saving."
        )


# --------------------------------------------------
# STORAGE
# --------------------------------------------------

def save_csv(records, path, fields=FIELDS):
    """Write rows to CSV (utf-8-sig so Excel shows umlauts correctly)."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    print("CSV saved:", display_path(path))


def display_path(path):
    """Path relative to the project root when inside it, else in full."""
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def connect():
    """Open the project database; it must already exist (step 01)."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"Database not found: {DB_PATH}. Run 01_init_database.py first."
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def save_database(records):
    """
    Insert records into discovery_candidates, or update existing rows.

    On conflict a column is only overwritten when the new value is not
    empty. A source that does not publish e.g. phone numbers therefore
    never wipes a phone number another step has already stored.
    """
    columns = ", ".join(FIELDS)
    placeholders = ", ".join(f":{field}" for field in FIELDS)
    updates = ", ".join(
        f"{field} = CASE WHEN excluded.{field} != '' "
        f"THEN excluded.{field} ELSE discovery_candidates.{field} END"
        for field in FIELDS
        if field not in KEY_FIELDS
    )

    with connect() as conn:
        conn.executemany(
            f"""
            INSERT INTO discovery_candidates ({columns})
            VALUES ({placeholders})
            ON CONFLICT ({", ".join(KEY_FIELDS)})
            DO UPDATE SET {updates}
            """,
            records,
        )

    print("Database updated:", len(records), "records")


# --------------------------------------------------
# CONSOLE OUTPUT
# --------------------------------------------------

LINE = "=" * 50


def print_banner(*lines):
    print(LINE)
    print(*lines, sep="\n")
    print(LINE)


def print_summary(title, records):
    """Print record counts and how complete each contact field is."""
    total = len(records)

    print()
    print_banner(title)
    print(f"{'Records:':<22}{total}")
    print(f"{'Unique companies:':<22}{len({r['company'].casefold() for r in records})}")

    for field in ("city", "website", "email", "phone"):
        filled = sum(bool(r[field]) for r in records)
        share = f" ({filled / total:.0%})" if total else ""
        print(f"{'With ' + field + ':':<22}{filled}{share}")

    print(LINE)
