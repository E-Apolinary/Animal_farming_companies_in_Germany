-- Singular test: descriptions in silver must not contain contact details.
-- dbt reports a failure for every row this query returns.
--
-- Guards the description cleaning in silver_discovery_candidates: if a source
-- changes its layout (e.g. a new "Fax:" format), the leftover text shows up
-- here instead of silently reaching gold.
--
-- A row fails when its description:
--   * still contains the link label "zur Website" (any case), or
--   * still STARTS with a contact piece: Tel/Telefon, E-Mail/Email,
--     Ansprechpartner, or a phone number beginning with + or 0

select
    id,
    company,
    source_name,
    description

from {{ ref('silver_discovery_candidates') }}

where lower(description) like '%zur website%'
   or lower(description) rlike '^(tel|e-?mail|ansprechpartner|[+0][0-9])'
