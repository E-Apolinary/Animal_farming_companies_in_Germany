"""
STEP 01: Create the project database.

Runs sql/schema.sql against data/database/animal_farming_germany_v2.db.
The schema only uses CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE, so
running this step on an existing database is safe: it adds missing
tables and never touches existing data.
"""

import sqlite3

import common
from common import SCHEMA_PATH, display_path, print_banner


def main():
    print_banner("ANIMAL FARMING GERMANY", "STEP 01: INITIALISE DATABASE")

    db_path = common.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

        print("Tables:")

        for (name,) in tables:
            rows = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
            print(f"  {name:<30}{rows:>6} rows")

    print("\nDatabase ready:", display_path(db_path))


if __name__ == "__main__":
    main()
