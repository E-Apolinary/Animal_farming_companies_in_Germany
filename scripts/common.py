"""Shared helpers for the discovery scripts."""

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data/database/animal_farming_germany_v2.db"
USER_AGENT = "Mozilla/5.0 (compatible; AnimalFarmingGermanyResearch/1.0)"

FIELDS = [
    "company", "sector", "city", "postal_code", "address", "website",
    "email", "phone", "description", "source_name", "source_url",
    "collected_at",
]


def clean(value):
    return " ".join(str(value).split())


def get_text(element, selector, squash=True):
    """Text of the first match; squash=True collapses inner whitespace."""
    found = element.select_one(selector)
    if not found:
        return ""
    text = found.get_text(" ", strip=True)
    return clean(text) if squash else text


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def fetch_soup(url, user_agent=USER_AGENT, session=None, timeout=60):
    response = (session or requests).get(
        url, headers={"User-Agent": user_agent}, timeout=timeout
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def dedupe(records):
    """Drop records that repeat the same company and address."""
    seen = set()
    unique = []
    for record in records:
        key = (record["company"].casefold(), record["address"].casefold())
        if key not in seen:
            seen.add(key)
            unique.append(record)
    return unique


def save_csv(records, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    print("CSV saved:", path)


def connect():
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    return sqlite3.connect(DB_PATH)


def save_database(records):
    """Upsert records into discovery_candidates."""
    with connect() as conn:
        conn.executemany(
            f"""
            INSERT INTO discovery_candidates ({", ".join(FIELDS)})
            VALUES ({", ".join("?" * len(FIELDS))})
            ON CONFLICT (source_name, company, address) DO UPDATE SET
                sector = excluded.sector,
                city = excluded.city,
                postal_code = excluded.postal_code,
                website = excluded.website,
                email = excluded.email,
                phone = excluded.phone,
                description = excluded.description,
                source_url = excluded.source_url,
                collected_at = excluded.collected_at
            """,
            [tuple(r[f] for f in FIELDS) for r in records],
        )
    print("Database updated successfully.")


def print_banner(*lines):
    print("=" * 45)
    print(*lines, sep="\n")
    print("=" * 45)
