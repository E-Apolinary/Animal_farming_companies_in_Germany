
import osmium #this is a library for working with OpenStreetMap data
import sqlite3
import json

from pathlib import Path
from datetime import datetime, timezone

# ==========================================
# 1. CONFIGURATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent

OSM_FILE = (
    BASE_DIR
    / "data"
    / "raw"
    / "saarland-latest.osm.pbf"
)

DB_PATH = (
    BASE_DIR
    / "data"
    / "database"
    / "animal_farming_germany.db"
)

if not OSM_FILE.exists():
    raise FileNotFoundError(OSM_FILE)

# ==========================================
# 2. DATABASE CONNECTION
# ==========================================

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS discovery_candidates (

    candidate_id TEXT PRIMARY KEY,
    source_name TEXT,
    source_url TEXT,
    company_name TEXT,
    city TEXT,
    postal_code TEXT,
    street TEXT,
    website TEXT,
    latitude REAL,
    longitude REAL,
    raw_tags TEXT,
    verification_status TEXT DEFAULT 'unverified',
    collected_at TEXT

)
""")

# ==========================================
# 3. OSM DATA HANDLER
# ==========================================

class FarmHandler(osmium.SimpleHandler):

    def __init__(self):
        super().__init__()
        self.records = []
        self.total_farmyards = 0

    def process(self, obj, osm_type):

        tags = dict(obj.tags)

        if tags.get("landuse") != "farmyard":
            return

        self.total_farmyards += 1

        name = tags.get("name", "").strip()

        if not name:
            return

        candidate_id = (
            f"osm:{osm_type}:{obj.id}"
        )

        latitude = None
        longitude = None

        # Nodes contain direct coordinates.
        # Ways and relations need separate
        # geometry processing.
        if osm_type == "node":
            if obj.location.valid():
                latitude = obj.location.lat
                longitude = obj.location.lon

        website = (
            tags.get("website")
            or tags.get("contact:website")
            or ""
        )

        self.records.append((
            candidate_id,
            "OpenStreetMap",
            f"https://www.openstreetmap.org/{osm_type}/{obj.id}",
            name,
            tags.get("addr:city", ""),
            tags.get("addr:postcode", ""),
            tags.get("addr:street", ""),
            website,
            latitude,
            longitude,
            json.dumps(tags, ensure_ascii=False),
            "unverified",
            datetime.now(timezone.utc).isoformat()
        ))

    def node(self, obj):
        self.process(obj, "node")

    def way(self, obj):
        self.process(obj, "way")

    def relation(self, obj):
        self.process(obj, "relation")


# ==========================================
# 4. PROCESS LOCAL OSM DATA
# ==========================================

print("Reading regional OSM data...")

handler = FarmHandler()

handler.apply_file(str(OSM_FILE))

print(
    "Total mapped farmyards:",
    handler.total_farmyards
)

print(
    "Named farm candidates:",
    len(handler.records)
)

# ==========================================
# 5. LOAD INTO SQLITE
# ==========================================

cursor.executemany("""
INSERT INTO discovery_candidates (

    candidate_id,
    source_name,
    source_url,
    company_name,
    city,
    postal_code,
    street,
    website,
    latitude,
    longitude,
    raw_tags,
    verification_status,
    collected_at

)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

ON CONFLICT(candidate_id) DO UPDATE SET

    company_name = excluded.company_name,
    city = excluded.city,
    postal_code = excluded.postal_code,
    street = excluded.street,
    website = excluded.website,
    latitude = excluded.latitude,
    longitude = excluded.longitude,
    raw_tags = excluded.raw_tags,
    collected_at = excluded.collected_at
""", handler.records)

conn.commit()

# ==========================================
# 6. VALIDATION
# ==========================================

cursor.execute("""
SELECT
    company_name,
    city,
    website
FROM discovery_candidates
LIMIT 10
""")

for row in cursor.fetchall():
    print(row)

cursor.execute("""
SELECT COUNT(*)
FROM discovery_candidates
""")

print(
    "\nTotal database candidates:",
    cursor.fetchone()[0]
)

conn.close()

print("\nLocal discovery completed!")

