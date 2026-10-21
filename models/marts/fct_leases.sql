-- Grain: one row per lease term
-- Only leases that passed validation. Rejected rows: see audit.rejected_records.
select
    l.lease_id,
    l.unit_id,
    u.property_id,
    l.resident_id,
    l.lease_start_date,
    l.lease_end_date,
    l.term_months,
    l.monthly_rent,
    l.security_deposit,
    l.move_out_date,
    l.lease_status,
    l.is_renewal,
    l.renewal_offer_pct,
    -- Rent change vs. this resident's previous lease in the same unit.
    -- Null for a resident's first lease (nothing to compare to).
    round(
        l.monthly_rent / lag(l.monthly_rent) over (
            partition by l.unit_id, l.resident_id order by l.lease_start_date
        ) - 1, 4
    )                                         as rent_change_pct
from intermediate.int_leases_validated l
join staging.stg_units u
    on l.unit_id = u.unit_id
where l.dq_issue is null
