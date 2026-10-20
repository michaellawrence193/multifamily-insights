-- Grain: one row per record that failed validation
-- Gives source-system owners a worklist of what to fix, and why.
select 'leases' as source_table, lease_id as record_id, dq_issue
from intermediate.int_leases_validated
where dq_issue is not null

union all

select 'work_orders', work_order_id, dq_issue
from intermediate.int_work_orders_validated
where dq_issue is not null
