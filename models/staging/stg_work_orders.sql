-- Grain: one row per maintenance request
select
    work_order_id,
    unit_id,
    category,
    priority,
    cast(opened_date as date)                 as opened_date,
    cast(completed_date as date)              as completed_date,
    status,
    cast(cost as decimal(10, 2))              as cost
from raw.work_orders
