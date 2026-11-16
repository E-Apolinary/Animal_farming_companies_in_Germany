-- =============================================================================
-- Silver: silver_discovery_candidates
-- =============================================================================
-- What this model does
--   Cleans the raw directory listings from bronze so they can be trusted and
--   matched later. It does NOT merge companies across sources.
--
-- Grain
--   One row per company per source directory (same as bronze).
--   A company listed by three associations appears here three times; that is
--   expected. Turning those listings into one real company is done in gold
--   (gold_companies), where the sources can be counted and compared.
--
-- Steps
--   1. source      read the raw bronze table
--   2. trimmed     trim all text, empty strings become NULL
--   3. normalised  standardise each field (sector, postcode, website, ...)
--   4. final       drop technical duplicates (same source listed it twice)
-- =============================================================================

with source as (

    select * from {{ source('bronze', 'discovery_candidates') }}

),


-- -----------------------------------------------------------------------------
-- Step 2: basic tidy-up
-- Remove leading/trailing spaces and turn empty strings into NULL, so that
-- "missing" always means NULL further down.
-- -----------------------------------------------------------------------------
trimmed as (

    select
        cast(id as bigint)                                      as id,

        -- company name: drop odd symbols (keep letters, digits, spaces and
        -- , ' & . -), then collapse repeated spaces into one
        regexp_replace(
            regexp_replace(trim(company), '[^\\p{L}\\p{N}\\s,''&.-]', ''),
            '\\s{2,}', ' '
        )                                                       as company,

        {%- for col in ['sector', 'city', 'address', 'website', 'email',
                        'phone', 'description', 'source_name', 'source_url'] %}
        nullif(trim(cast({{ col }} as string)), '')             as {{ col }},
        {%- endfor %}

        -- postcode: keep digits only, because the CSV upload may have read
        -- it as a number (e.g. 1234.0 instead of "01234")
        regexp_replace(cast(postal_code as string), '[^0-9]', '') as postal_digits,

        cast(collected_at as timestamp)                         as collected_at

    from source

),


-- -----------------------------------------------------------------------------
-- Step 3: standardise each field
-- Bring every field into one consistent format, so the same company looks
-- the same no matter which directory it came from.
-- -----------------------------------------------------------------------------
normalised as (

    select
        id,
        company,

        -- some sources only give a placeholder sector ending in
        -- "- ... Unverified"; keep the sector name and flag it instead
        trim(regexp_replace(sector, ' - [^-]*Unverified$', ''))  as sector,
        coalesce(sector not like '%Unverified', false)          as is_sector_verified,

        city,

        -- German postcodes have 5 digits; a 4-digit value lost its leading
        -- zero (e.g. Dresden 01067 -> 1067), anything else is invalid
        case
            when length(postal_digits) = 5 then postal_digits
            when length(postal_digits) = 4 then lpad(postal_digits, 5, '0')
        end                                                     as postal_code,

        address,

        -- website reduced to the bare domain, e.g.
        -- "https://www.example.de/about" -> "example.de"
        nullif(
            regexp_extract(lower(website), '^(https?://)?(www[.])?([^/?#]+)', 3), 
            ''
        )                                                       as website,

        -- email in lower case; NULL when it does not look like an address
        case
            when lower(email) rlike '^[^@ ]+@[^@ ]+[.][^@ ]+$' then lower(email)
        end                                                     as email,

        -- phone reduced to digits and a leading "+",
        -- e.g. "+49 (0)30 123-45" -> "+4903012345"
        nullif(regexp_replace(phone, '[^0-9+]', ''), '')        as phone,

        description,

        -- where the row came from; gold uses these to count and list sources
        source_name,
        source_url,
       cast(collected_at as timestamp)                         as collected_at

    from trimmed

)


-- -----------------------------------------------------------------------------
-- Step 4: remove technical duplicates only
-- If the SAME source lists the same company in the same city more than once,
-- that is a scraping/upload repeat, so keep one row (the most recent).
-- The same company from DIFFERENT sources is kept here on purpose; it is
-- merged in gold.
-- -----------------------------------------------------------------------------
select *
from normalised
qualify row_number() over (
            partition by source_name, lower(company), lower(city)
            order by collected_at desc, id
        ) = 1 
