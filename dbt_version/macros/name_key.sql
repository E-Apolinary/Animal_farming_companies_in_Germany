-- macros/name_key.sql
-- Normalised company name used to match listings across sources.
-- Must stay identical to the rule in scripts/20_resolve_companies.py.
{% macro name_key(column) %}
    trim(regexp_replace(
        regexp_replace(lower({{ column }}), '[^\\p{L}\\p{N}_\\s]', ' '),
        '\\s+', ' '
    ))
{% endmacro %}
