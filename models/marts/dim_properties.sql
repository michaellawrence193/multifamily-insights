-- Grain: one row per property
select
    property_id,
    property_name,
    city,
    state_code,
    property_type,
    unit_count,
    year_built
from staging.stg_properties
