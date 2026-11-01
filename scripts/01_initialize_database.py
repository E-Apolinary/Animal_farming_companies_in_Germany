
import sqlite3 #store data in a local database
from pathlib import Path

# ==========================================
# 1. DATABASE LOCATION
# ==========================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "database" / "animal_farming_germany.db"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ==========================================
# 2. CONNECT TO SQLITE
# ==========================================

conn = sqlite3.connect(DB_PATH) # Connect to the SQLite database

conn.execute("PRAGMA foreign_keys = ON") #Enable foreign key support

cursor = conn.cursor() # Create a cursor object, a cursor is used to execute SQL commands

# ==========================================
# 3. CREATE COMPANIES TABLE
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS companies (

    company_id INTEGER PRIMARY KEY AUTOINCREMENT,

    company_name TEXT NOT NULL,

    legal_name TEXT,

    company_description TEXT,

    headquarters_city TEXT,

    headquarters_state TEXT,

    website TEXT,

    career_page TEXT,

    linkedin_url TEXT,

    employee_count INTEGER,

    employee_count_year INTEGER,

    revenue_eur REAL,

    revenue_year INTEGER,

    founding_year INTEGER,

    company_status TEXT DEFAULT 'unverified',

    last_updated TEXT

)
""")

# ==========================================
# 4. CREATE SECTORS TABLE
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS sectors (

    sector_id TEXT PRIMARY KEY,

    sector_name TEXT NOT NULL,

    sector_description TEXT

)
""")

# ==========================================
# 5. COMPANY-SECTOR RELATIONSHIPS
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS company_sectors (

    company_id INTEGER,

    sector_id TEXT,

    PRIMARY KEY (company_id, sector_id),

    FOREIGN KEY (company_id)
        REFERENCES companies(company_id),

    FOREIGN KEY (sector_id)
        REFERENCES sectors(sector_id)

)
""")

# ==========================================
# 6. COMPANY LOCATIONS
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS locations (

    location_id INTEGER PRIMARY KEY AUTOINCREMENT,

    company_id INTEGER NOT NULL,

    city TEXT,

    federal_state TEXT,

    street_address TEXT,

    postal_code TEXT,

    location_type TEXT,

    FOREIGN KEY (company_id)
        REFERENCES companies(company_id)

)
""")

# ==========================================
# 7. JOB OPPORTUNITIES
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS jobs (

    job_id INTEGER PRIMARY KEY AUTOINCREMENT,

    company_id INTEGER NOT NULL,

    job_title TEXT,

    job_location TEXT,

    employment_type TEXT,

    career_level TEXT,

    remote_option TEXT,

    salary_min REAL,

    salary_max REAL,

    job_url TEXT,

    date_posted TEXT,

    date_collected TEXT,

    FOREIGN KEY (company_id)
        REFERENCES companies(company_id)

)
""")

# ==========================================
# 8. DATA SOURCES
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS sources (

    source_id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_name TEXT,

    source_type TEXT,

    source_url TEXT,

    date_accessed TEXT

)
""")

# ==========================================
# 9. COMPANY-SOURCE RELATIONSHIPS
# ==========================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS company_sources (

    company_id INTEGER,

    source_id INTEGER,

    PRIMARY KEY (company_id, source_id),

    FOREIGN KEY (company_id)
        REFERENCES companies(company_id),

    FOREIGN KEY (source_id)
        REFERENCES sources(source_id)

)
""")

# ==========================================
# 10. INSERT INDUSTRY SECTORS
# ==========================================

sectors = [
    ("AF01", "Dairy farming"),
    ("AF02", "Cattle farming"),
    ("AF03", "Pig farming"),
    ("AF04", "Poultry farming"),
    ("AF05", "Sheep and goat farming"),
    ("AF06", "Other livestock"),
    ("AF07", "Animal breeding and genetics"),
    ("AF08", "Animal feed and nutrition"),
    ("AF09", "Animal health"),
    ("AF10", "Livestock equipment"),
    ("AF11", "AgriTech and automation"),
    ("AF12", "Agricultural services"),
    ("AF13", "Meat and dairy processing"),
    ("AF14", "Agricultural energy"),
    ("AF15", "Distribution and trade"),
    ("AF16", "Research and education")
]

cursor.executemany("""
INSERT OR IGNORE INTO sectors (
    sector_id,
    sector_name
)
VALUES (?, ?)
""", sectors)

# ==========================================
# 11. SAVE DATABASE
# ==========================================

conn.commit()

# ==========================================
# 12. VERIFY DATABASE STRUCTURE
# ==========================================

cursor.execute("""
SELECT name
FROM sqlite_master
WHERE type = 'table'
ORDER BY name
""")

tables = cursor.fetchall()

print("\nDATABASE TABLES")

for table in tables:
    print("-", table[0])

cursor.execute(
    "SELECT COUNT(*) FROM sectors"
)

print(
    "\nNumber of sectors:",
    cursor.fetchone()[0]
)

print("\nDatabase saved to:")
print(DB_PATH)

conn.close()

print("\nPhase 1 initialization completed!")
