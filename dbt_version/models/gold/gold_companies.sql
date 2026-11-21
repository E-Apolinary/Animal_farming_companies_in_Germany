-- =============================================================================
-- Gold: gold_companies
-- =============================================================================
-- What this model does
--   The final company list. Silver has one row per company PER DIRECTORY, so
--   a dairy listed by MIV and Export-Union appears twice there. This model
--   merges those listings into one row per real company.
--
-- Grain
--   One row per company_id.
--
-- How listings are matched
--   Same rule as the Python pipeline (scripts/20_resolve_companies.py):
--   two listings are the same company when their normalised names are equal.
--   Normalising ignores case, punctuation and repeated spaces, so
--       "Müller GmbH & Co. KG"  and  "MÜLLER GmbH & Co KG"
--   both become the key "müller gmbh co kg".
--
-- How the fields are chosen when sources disagree
--   * Name: from the FIRST listing (lowest silver id), so the name does not
--     change when a new source is added.
--   * Contact and location fields: from the first listing that HAS a value.
--     A later source can fill a gap but never overwrites a known value.
--   * Sectors and sources: all distinct values are kept, joined with " | ".
--
-- Steps
--   1. listings    read silver
--   2. keyed       build the matching key and company_id for each listing
--   3. merged      group listings into one row per company
--   4. final       flag companies that share a website with another company
-- =============================================================================

with listings as (

    select * from {{ ref('silver_discovery_candidates') }}

),


-- -----------------------------------------------------------------------------
-- Step 2: matching key and company ID
--
-- name_key, read from the inside out:
--   lower(...)                 ignore upper/lower case
--   [^\p{L}\p{N}_\s] -> ' '    anything that is not a letter, digit,
--                              underscore or space becomes a space
--                              (same as Python's [^\w\s])
--   \s+ -> ' ' and trim        collapse runs of spaces, strip the ends
-- Note: Python also applies Unicode NFKC and casefold (ß -> ss). Spark SQL
-- has no equivalent, so names differing only by "ß" vs "ss" stay separate.
--
-- company_id = 'COMP_' + first 20 hex characters of SHA-256(name_key).
-- The same name always gives the same ID, so IDs are stable across runs and
-- identical to the IDs produced by the Python pipeline.
-- -----------------------------------------------------------------------------
keyed as (
    select
        *,
        {{ name_key('company') }}   as name_key
    from listings
),


with_ids as (

    select
        concat('COMP_', left(sha2(name_key, 256), 20))          as company_id,
        *

    from keyed
    where name_key <> ''    -- a name made only of symbols cannot be matched

),


-- -----------------------------------------------------------------------------
-- Step 3: one row per company
--
-- min_by(value, order) returns the value from the row with the smallest
-- "order". Rows where "order" is NULL are skipped. So
--     min_by(city, case when city is not null then id end)
-- means "the city from the earliest listing that has a city".
-- -----------------------------------------------------------------------------
merged as (

    select
        company_id,

        -- name from the very first listing
        min_by(company, id)                                     as company_name,

        -- first known value for each contact / location field
        {%- for col in ['city', 'postal_code', 'address', 'website',
                        'email', 'phone', 'description'] %}
        min_by({{ col }}, case when {{ col }} is not null then id end) as {{ col }},
        {%- endfor %}

        -- every sector the company was listed under, e.g.
        -- "Dairy processing | Dairy value chain"
        array_join(array_sort(collect_set(sector)), ' | ')      as sectors,

        -- true when at least one source gave a real (not placeholder) sector
        bool_or(is_sector_verified)                             as is_sector_verified,

        -- which directories list the company, and how many
        array_join(array_sort(collect_set(source_name)), ' | ') as sources,
        count(distinct source_name)                             as source_count,

        -- lineage: the silver ids that were merged into this company
        array_join(array_sort(collect_list(cast(id as string))), ' | ')
                                                                as silver_ids,
        count(*)                                                as listing_count,

        min(collected_at)                                       as first_collected_at,
        max(collected_at)                                       as last_collected_at

    from with_ids
    group by company_id

)


-- -----------------------------------------------------------------------------
-- Step 4: final columns
-- Name matching cannot catch related companies with different names, e.g.
-- "Company GmbH" and "Company Deutschland GmbH". When two or more companies
-- share the same website domain they are flagged for manual review instead
-- of being merged automatically.
-- -----------------------------------------------------------------------------
select
    *,

    -- confirmed by two or more independent directories
    source_count > 1                                            as is_multi_source,

    -- true when another company in this table has the same website domain
    coalesce(
        count(*) over (partition by website) > 1 and website is not null,
        false
    )                                                           as shares_website

from merged
