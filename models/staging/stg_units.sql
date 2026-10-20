-- Grain: one row per unit
select
    unit_id,
    property_id,
    unit_number,
    cast(bedrooms as integer)                 as bedrooms,
    cast(bathrooms as integer)                as bathrooms,
    cast(square_feet as integer)              as square_feet,
    cast(floor as integer)                    as floor,
    cast(market_rent as decimal(10, 2))       as market_rent
from raw.units
