-- Grain: one row per unit per month (a month-end "snapshot")
-- Answers: was this unit occupied on the last day of the month, and at what rent?
--
-- Known limitation: starts January 2023. Units' first leases are staggered
-- across 2022, so 2022 would look like a building lease-up rather than
-- normal operations. Rejected leases (see audit) can also show a unit as
-- vacant for months it was really occupied.
with months as (
    select cast(month_start as date) as month_start,
           cast(month_start + interval 1 month - interval 1 day as date) as month_end
    from generate_series(date '2023-01-01', date '2026-09-01', interval 1 month) as t(month_start)
),

unit_months as (
    select u.unit_id, u.property_id, u.market_rent, m.month_start, m.month_end
    from marts.dim_units u
    cross join months m
)

select
    um.unit_id,
    um.property_id,
    um.month_start,
    l.lease_id is not null                    as is_occupied,
    l.lease_id,
    l.monthly_rent,
    um.market_rent
from unit_months um
left join marts.fct_leases l
    on  l.unit_id = um.unit_id
    and um.month_end between l.lease_start_date
                         and coalesce(l.move_out_date, l.lease_end_date)
