-- Grain: one row per lease term
-- The source export contains exact duplicate rows (an ETL/sync bug).
-- We keep one row per lease_id so the grain holds downstream.
select
    lease_id,
    unit_id,
    resident_id,
    cast(lease_start_date as date)            as lease_start_date,
    cast(lease_end_date as date)              as lease_end_date,
    cast(term_months as integer)              as term_months,
    cast(monthly_rent as decimal(10, 2))      as monthly_rent,
    cast(security_deposit as decimal(10, 2))  as security_deposit,
    cast(move_out_date as date)               as move_out_date,
    lease_status,
    cast(is_renewal as boolean)               as is_renewal
from raw.leases
qualify row_number() over (partition by lease_id order by lease_start_date) = 1
