-- Silver: cleaned discovery candidates.
-- One row per company per source directory, same grain as bronze.
-- Text is trimmed (empty strings become NULL) and contact fields are
-- normalised so companies can be matched across sources downstream.

with source as (

    select * from {{ source('bronze', 'discovery_candidates') }}

),

cleaned  as (

    select
     cast(id as bigint)                                                                            as id,
     regexp_replace( regexp_replace(trim(company), '[^\\p{L}\\p{N}\\s,''&.-]', ''), '\\s{2,}',' ') as company,

     {%- for col in ['sector', 'city', 'address', 'website', 'email',
                        'phone'] %}
     nullif(trim(cast({{ col }} as string)), '')                                                   as {{ col }},
     {%- endfor %}
     -- keep digits only; the CSV upload may have read it as a number
     regexp_replace(cast(postal_code as string), '[^0-9]', '')                                    as postal_digits

     from source

)

select
    id,
    company,

    -- sector without the "- ... Unverified" suffix, plus a flag for it
    trim(regexp_replace(sector, ' - [^-]*Unverified$', ''))                                        as sector,
    sector not like '%Unverified'                                                                  as is_sector_verified,

    city,
    -- German postcodes are 5 digits; restore a dropped leading zero
    case
        when length(postal_digits) = 5 then postal_digits
        when length(postal_digits) = 4 then lpad(postal_digits, 5, '0')
    end                                                                                            as postal_code,
    
    address,

    -- bare domain (no protocol, www or path) for cross-source matching
    nullif(regexp_extract(lower(website), '^(https?://)?(www[.])?([^/?#]+)', 3), '')
                                                                                                   as website,

    -- lower-cased, NULL when it is not a plausible address
    case
        when lower(email) rlike '^[^@ ]+@[^@ ]+[.][^@ ]+$' then lower(email)
    end                                                                                             as email,

    nullif(regexp_replace(phone, '[^0-9+]', ''), '')                                                 as phone

from cleaned