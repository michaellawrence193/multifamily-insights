-- Grain: one row per lease term (same as stg_leases)
-- Job: run business-rule checks and label each failing row with the reason.
-- Valid rows (dq_issue is null) flow to marts; invalid rows go to the audit table.
-- We flag rather than silently drop, so nothing disappears without a trace.
select
    l.*,
    case
        when u.unit_id is null                      then 'unit_id not found in units'
        when l.lease_end_date < l.lease_start_date  then 'lease ends before it starts'
        when l.monthly_rent <= 0                    then 'monthly_rent is zero or negative'
    end                                             as dq_issue
from staging.stg_leases l
left join staging.stg_units u
    on l.unit_id = u.unit_id
