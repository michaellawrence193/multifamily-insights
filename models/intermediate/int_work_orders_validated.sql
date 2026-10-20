-- Grain: one row per maintenance request
select
    w.*,
    case
        when u.unit_id is null                      then 'unit_id not found in units'
        when w.completed_date < w.opened_date       then 'completed before opened'
    end                                             as dq_issue
from staging.stg_work_orders w
left join staging.stg_units u
    on w.unit_id = u.unit_id
