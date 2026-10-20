-- Grain: one row per maintenance request
select
    w.work_order_id,
    w.unit_id,
    u.property_id,
    w.category,
    w.priority,
    w.opened_date,
    w.completed_date,
    w.status,
    w.cost,
    date_diff('day', w.opened_date, w.completed_date) as days_to_complete
from intermediate.int_work_orders_validated w
join staging.stg_units u
    on w.unit_id = u.unit_id
where w.dq_issue is null
