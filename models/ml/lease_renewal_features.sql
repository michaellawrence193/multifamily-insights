-- Grain: one row per lease term
-- Purpose: one row of model inputs ("features") per lease, plus the outcome
-- we want to predict ("label"): did the resident renew?
--
-- Leases that have ended (Renewed / Moved Out) have a label and are used to
-- TRAIN the model. Active leases have no label yet; those are the ones we
-- SCORE to predict who is at risk of leaving.
--
-- The golden rule: every feature must be something the property team would
-- know BEFORE the resident decides. Anything learned after the decision
-- (like the rent on a resident's next lease) would be "data leakage": the
-- model would look brilliant in testing and be useless in real life.
--
-- Simplification: work orders are counted across the whole lease. In reality
-- the renewal decision happens ~60 days before the lease ends, so a stricter
-- version would only count work orders up to that point.

with resident_tenure as (
    -- When did this resident first move into this unit?
    select unit_id, resident_id, min(lease_start_date) as tenure_start
    from marts.fct_leases
    group by unit_id, resident_id
),

lease_work_orders as (
    select
        l.lease_id,
        count(w.work_order_id)                               as work_order_count,
        count(w.work_order_id) filter (where w.priority in ('High', 'Emergency'))
                                                             as urgent_work_order_count,
        coalesce(avg(w.days_to_complete), 0)                 as avg_days_to_complete
    from marts.fct_leases l
    left join marts.fct_work_orders w
        on  w.unit_id = l.unit_id
        and w.opened_date between l.lease_start_date and l.lease_end_date
    group by l.lease_id
)

select
    l.lease_id,
    l.unit_id,
    l.property_id,
    l.resident_id,
    l.lease_start_date,
    l.lease_end_date,

    -- Lease features
    l.term_months,
    l.monthly_rent,
    l.renewal_offer_pct,
    date_diff('month', t.tenure_start, l.lease_end_date)     as tenure_months,
    l.is_renewal                                             as is_already_renewed_once,

    -- Maintenance experience during the lease
    wo.work_order_count,
    wo.urgent_work_order_count,
    wo.avg_days_to_complete,

    -- Unit and property
    u.bedrooms,
    u.square_feet,
    u.property_type,
    u.city,

    -- Resident (non-PII bands only)
    r.age_band,
    r.income_band,

    -- Label: null for active leases (outcome not known yet)
    case l.lease_status
        when 'Renewed'   then 1
        when 'Moved Out' then 0
    end                                                      as renewed
from marts.fct_leases l
join resident_tenure t
    on l.unit_id = t.unit_id and l.resident_id = t.resident_id
join lease_work_orders wo
    on l.lease_id = wo.lease_id
join marts.dim_units u
    on l.unit_id = u.unit_id
join marts.dim_residents r
    on l.resident_id = r.resident_id
