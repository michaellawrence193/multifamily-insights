-- Grain: one row per resident
-- Governance: no names, emails, phone numbers or birth dates here. Analysts and
-- AI tools get useful attributes (age band, income band) without personal data.
select
    resident_id,
    case
        when date_diff('year', date_of_birth, date '2026-10-01') < 30 then 'Under 30'
        when date_diff('year', date_of_birth, date '2026-10-01') < 45 then '30-44'
        when date_diff('year', date_of_birth, date '2026-10-01') < 60 then '45-59'
        else '60+'
    end                                       as age_band,
    case
        when annual_income < 60000  then 'Under $60K'
        when annual_income < 90000  then '$60K-$90K'
        when annual_income < 120000 then '$90K-$120K'
        else '$120K+'
    end                                       as income_band,
    email is not null                         as has_email_on_file,
    created_date                              as first_move_in_date
from staging.stg_residents
