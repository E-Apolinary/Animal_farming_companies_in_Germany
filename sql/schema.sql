-- ==================================================================
-- Animal Farming Germany: database schema
--
-- Every statement uses IF NOT EXISTS, so running this file against an
-- existing database is safe: it only adds what is missing.
--
-- Layers
--   1. Staging      discovery_candidates   one row per company per source
--   2. Enrichment   company_relevance, company_activity_enrichment
--   3. Resolved     resolved_companies (+ sectors, sources)
--                   one row per real company, merged across sources
--   4. Target model companies, locations, jobs, ... (planned, not yet filled)
-- ==================================================================


-- ------------------------------------------------------------------
-- 1. STAGING: raw company records from the member directories
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company       TEXT NOT NULL,
    sector        TEXT,
    city          TEXT,
    postal_code   TEXT,
    address       TEXT,
    website       TEXT,
    email         TEXT,
    phone         TEXT,
    description   TEXT,
    source_name   TEXT NOT NULL,
    source_url    TEXT NOT NULL,
    collected_at  TEXT,

    -- The same company listed twice by one source is stored once.
    UNIQUE (source_name, company, address)
);


-- ------------------------------------------------------------------
-- 2. ENRICHMENT: evidence gathered from company websites
-- ------------------------------------------------------------------

-- First pass over VDMA machinery makers: homepage keyword check.
CREATE TABLE IF NOT EXISTS company_relevance (
    discovery_id           INTEGER PRIMARY KEY,
    company                TEXT,
    relevance              TEXT,   -- direct | indirect | crop_focused | unknown
    matched_keywords       TEXT,
    evidence_url           TEXT,
    classification_status  TEXT,   -- success | request_failed | ...
    checked_at             TEXT,
    FOREIGN KEY (discovery_id) REFERENCES discovery_candidates (id)
);

-- Second pass for companies the first pass left "unknown":
-- homepage plus up to three relevant sub-pages.
CREATE TABLE IF NOT EXISTS company_activity_enrichment (
    discovery_id       INTEGER PRIMARY KEY,
    company            TEXT,
    classification     TEXT,
    direct_keywords    TEXT,
    indirect_keywords  TEXT,
    crop_keywords      TEXT,
    evidence_urls      TEXT,
    pages_analyzed     INTEGER,
    status             TEXT,
    enriched_at        TEXT,
    FOREIGN KEY (discovery_id) REFERENCES discovery_candidates (id)
);


-- ------------------------------------------------------------------
-- 3. RESOLVED: one row per real-world company
-- ------------------------------------------------------------------

-- company_id is a hash of the normalised name, so it stays stable
-- between runs.
CREATE TABLE IF NOT EXISTS resolved_companies (
    company_id       TEXT PRIMARY KEY,
    company_name     TEXT NOT NULL,
    normalized_name  TEXT NOT NULL UNIQUE,
    website          TEXT,
    city             TEXT
);

-- A company can be active in several sectors.
CREATE TABLE IF NOT EXISTS resolved_company_sectors (
    company_id  TEXT NOT NULL,
    sector      TEXT NOT NULL,
    PRIMARY KEY (company_id, sector),
    FOREIGN KEY (company_id) REFERENCES resolved_companies (company_id)
);

-- Links every staging row back to its resolved company (lineage).
CREATE TABLE IF NOT EXISTS resolved_company_sources (
    company_id    TEXT NOT NULL,
    discovery_id  INTEGER NOT NULL UNIQUE,
    source_name   TEXT NOT NULL,
    PRIMARY KEY (company_id, discovery_id),
    FOREIGN KEY (company_id) REFERENCES resolved_companies (company_id)
);


-- ------------------------------------------------------------------
-- 4. TARGET MODEL (planned): verified companies, sites and jobs
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS companies (
    company_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name         TEXT NOT NULL,
    legal_name           TEXT,
    company_description  TEXT,
    headquarters_city    TEXT,
    headquarters_state   TEXT,
    website              TEXT,
    career_page          TEXT,
    linkedin_url         TEXT,
    employee_count       INTEGER,
    employee_count_year  INTEGER,
    revenue_eur          REAL,
    revenue_year         INTEGER,
    founding_year        INTEGER,
    company_status       TEXT DEFAULT 'unverified',
    last_updated         TEXT
);

CREATE TABLE IF NOT EXISTS sectors (
    sector_id           TEXT PRIMARY KEY,
    sector_name         TEXT NOT NULL,
    sector_description  TEXT
);

CREATE TABLE IF NOT EXISTS company_sectors (
    company_id  INTEGER,
    sector_id   TEXT,
    PRIMARY KEY (company_id, sector_id),
    FOREIGN KEY (company_id) REFERENCES companies (company_id),
    FOREIGN KEY (sector_id) REFERENCES sectors (sector_id)
);

CREATE TABLE IF NOT EXISTS locations (
    location_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      INTEGER NOT NULL,
    city            TEXT,
    federal_state   TEXT,
    street_address  TEXT,
    postal_code     TEXT,
    location_type   TEXT,
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id       INTEGER NOT NULL,
    job_title        TEXT,
    job_location     TEXT,
    employment_type  TEXT,
    career_level     TEXT,
    remote_option    TEXT,
    salary_min       REAL,
    salary_max       REAL,
    job_url          TEXT,
    date_posted      TEXT,
    date_collected   TEXT,
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE IF NOT EXISTS sources (
    source_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name    TEXT,
    source_type    TEXT,
    source_url     TEXT,
    date_accessed  TEXT
);

CREATE TABLE IF NOT EXISTS company_sources (
    company_id  INTEGER,
    source_id   INTEGER,
    PRIMARY KEY (company_id, source_id),
    FOREIGN KEY (company_id) REFERENCES companies (company_id),
    FOREIGN KEY (source_id) REFERENCES sources (source_id)
);


-- ------------------------------------------------------------------
-- REFERENCE DATA: the 16 sectors of the animal farming value chain
-- ------------------------------------------------------------------

INSERT OR IGNORE INTO sectors (sector_id, sector_name) VALUES
    ('AF01', 'Dairy farming'),
    ('AF02', 'Cattle farming'),
    ('AF03', 'Pig farming'),
    ('AF04', 'Poultry farming'),
    ('AF05', 'Sheep and goat farming'),
    ('AF06', 'Other livestock'),
    ('AF07', 'Animal breeding and genetics'),
    ('AF08', 'Animal feed and nutrition'),
    ('AF09', 'Animal health'),
    ('AF10', 'Livestock equipment'),
    ('AF11', 'AgriTech and automation'),
    ('AF12', 'Agricultural services'),
    ('AF13', 'Meat and dairy processing'),
    ('AF14', 'Agricultural energy'),
    ('AF15', 'Distribution and trade'),
    ('AF16', 'Research and education');
