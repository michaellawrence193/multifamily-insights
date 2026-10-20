-- Grain: one row per resident
-- Note: this table holds PII (names, email, phone, birth date, income).
-- It stays in staging; the marts layer exposes only non-identifying attributes.
select
    resident_id,
    first_name,
    last_name,
    lower(trim(email))                        as email,
    phone,
    cast(date_of_birth as date)               as date_of_birth,
    cast(annual_income as integer)            as annual_income,
    cast(created_date as date)                as created_date
from raw.residents
