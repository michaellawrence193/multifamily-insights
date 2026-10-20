-- Grain: one row per unit
-- Property attributes are copied onto each unit ("denormalized") so dashboard
-- users can filter units by city or property type without writing a join.
select
    u.unit_id,
    u.unit_number,
    u.bedrooms,
    case u.bedrooms when 0 then 'Studio' else u.bedrooms || ' BR' end as floorplan,
    u.bathrooms,
    u.square_feet,
    u.floor,
    u.market_rent,
    p.property_id,
    p.property_name,
    p.city,
    p.state_code,
    p.property_type
from staging.stg_units u
join staging.stg_properties p
    on u.property_id = p.property_id
