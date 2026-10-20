-- Grain: one row per property (apartment community)
-- Job: clean and standardize, 1:1 with raw.properties. No joins, no filtering.
select
    property_id,
    trim(property_name)                       as property_name,
    trim(city)                                as city,
    -- Source system allowed free-text states ('ga', 'Texas'). Standardize to
    -- 2-letter uppercase codes so grouping by state doesn't split one state in two.
    case upper(trim(state))
        when 'TEXAS'          then 'TX'
        when 'GEORGIA'        then 'GA'
        when 'SOUTH CAROLINA' then 'SC'
        when 'NORTH CAROLINA' then 'NC'
        when 'COLORADO'       then 'CO'
        else upper(trim(state))
    end                                       as state_code,
    property_type,
    cast(unit_count as integer)               as unit_count,
    cast(year_built as integer)               as year_built
from raw.properties
