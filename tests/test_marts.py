"""
Tests that the marts are trustworthy: the tables dashboards and models use.

These are the same "generic tests" dbt ships with -- unique, not_null,
relationships, accepted_values -- written in plain pytest. Each test is a
SQL query that should return ZERO problem rows.

@pytest.mark.parametrize runs one test function once per entry in the list,
so adding a new table to check is a one-line change.
"""

import pytest

# ---------------------------------------------------------------------------
# Grain: every primary key is unique and never null
# ---------------------------------------------------------------------------
PRIMARY_KEYS = [
    ("marts.dim_properties", "property_id"),
    ("marts.dim_units", "unit_id"),
    ("marts.dim_residents", "resident_id"),
    ("marts.fct_leases", "lease_id"),
    ("marts.fct_work_orders", "work_order_id"),
    # Composite key: one row per unit per month
    ("marts.fct_unit_occupancy_monthly", "unit_id, month_start"),
]


@pytest.mark.parametrize("table, key", PRIMARY_KEYS)
def test_primary_key_is_unique(con, table, key):
    duplicates = con.execute(f"""
        select {key}, count(*) as n
        from {table}
        group by {key}
        having count(*) > 1
    """).fetchall()
    assert duplicates == [], f"{table} has duplicate keys, e.g. {duplicates[:3]}"


@pytest.mark.parametrize("table, key", PRIMARY_KEYS)
def test_primary_key_is_not_null(con, table, key):
    null_check = " or ".join(f"{col.strip()} is null" for col in key.split(","))
    n = con.execute(f"select count(*) from {table} where {null_check}").fetchone()[0]
    assert n == 0, f"{table} has {n} rows with a null key"


# ---------------------------------------------------------------------------
# Referential integrity: every foreign key points at a row that exists
# ---------------------------------------------------------------------------
FOREIGN_KEYS = [
    # (child table, child column, parent table, parent column)
    ("marts.dim_units", "property_id", "marts.dim_properties", "property_id"),
    ("marts.fct_leases", "unit_id", "marts.dim_units", "unit_id"),
    ("marts.fct_leases", "resident_id", "marts.dim_residents", "resident_id"),
    ("marts.fct_leases", "property_id", "marts.dim_properties", "property_id"),
    ("marts.fct_work_orders", "unit_id", "marts.dim_units", "unit_id"),
    ("marts.fct_unit_occupancy_monthly", "unit_id", "marts.dim_units", "unit_id"),
]


@pytest.mark.parametrize("child, child_col, parent, parent_col", FOREIGN_KEYS)
def test_foreign_key_has_parent(con, child, child_col, parent, parent_col):
    orphans = con.execute(f"""
        select distinct c.{child_col}
        from {child} c
        left join {parent} p on c.{child_col} = p.{parent_col}
        where p.{parent_col} is null
    """).fetchall()
    assert orphans == [], f"{child}.{child_col} has orphans: {orphans[:5]}"


# ---------------------------------------------------------------------------
# Accepted values: categorical columns only contain known values
# ---------------------------------------------------------------------------
ACCEPTED_VALUES = [
    ("marts.dim_properties", "state_code", {"SC", "GA", "TX", "NC", "CO"}),
    ("marts.fct_leases", "lease_status", {"Active", "Renewed", "Moved Out"}),
    ("marts.fct_work_orders", "priority", {"Low", "Medium", "High", "Emergency"}),
    ("marts.fct_work_orders", "status", {"Open", "Completed"}),
]


@pytest.mark.parametrize("table, column, allowed", ACCEPTED_VALUES)
def test_accepted_values(con, table, column, allowed):
    actual = {row[0] for row in con.execute(f"select distinct {column} from {table}").fetchall()}
    unexpected = actual - allowed
    assert not unexpected, f"{table}.{column} has unexpected values: {unexpected}"


# ---------------------------------------------------------------------------
# Business rules
# ---------------------------------------------------------------------------
BUSINESS_RULES = [
    # (description, query returning rows that BREAK the rule)
    ("lease ends on or after it starts",
     "select lease_id from marts.fct_leases where lease_end_date < lease_start_date"),
    ("rent is positive",
     "select lease_id from marts.fct_leases where monthly_rent <= 0"),
    ("work order completed on or after it opened",
     "select work_order_id from marts.fct_work_orders where completed_date < opened_date"),
    ("completed work orders have a completion date",
     "select work_order_id from marts.fct_work_orders where status = 'Completed' and completed_date is null"),
    ("a unit never has two overlapping leases",
     """select a.lease_id from marts.fct_leases a
        join marts.fct_leases b
          on a.unit_id = b.unit_id and a.lease_id < b.lease_id
         and a.lease_start_date <= coalesce(b.move_out_date, b.lease_end_date)
         and b.lease_start_date <= coalesce(a.move_out_date, a.lease_end_date)"""),
    ("rent is within a plausible range of market rent",
        """select l.lease_id
        from marts.fct_leases l
        join marts.dim_units u on u.unit_id = l.unit_id
        where l.monthly_rent > u.market_rent * 2
        or l.monthly_rent < u.market_rent / 2"""),
]


@pytest.mark.parametrize("rule, sql", BUSINESS_RULES, ids=[r[0] for r in BUSINESS_RULES])
def test_business_rule(con, rule, sql):
    violations = con.execute(sql).fetchall()
    assert violations == [], f"Rule broken ({rule}): {violations[:5]}"


# ---------------------------------------------------------------------------
# Reconciliation: no rows lost or invented between layers
# ---------------------------------------------------------------------------
def test_leases_reconcile_across_layers(con):
    staged = con.execute("select count(*) from staging.stg_leases").fetchone()[0]
    in_mart = con.execute("select count(*) from marts.fct_leases").fetchone()[0]
    rejected = con.execute(
        "select count(*) from audit.rejected_records where source_table = 'leases'"
    ).fetchone()[0]
    assert staged == in_mart + rejected, (
        f"{staged} staged leases != {in_mart} in mart + {rejected} rejected"
    )


def test_work_orders_reconcile_across_layers(con):
    staged = con.execute("select count(*) from staging.stg_work_orders").fetchone()[0]
    in_mart = con.execute("select count(*) from marts.fct_work_orders").fetchone()[0]
    rejected = con.execute(
        "select count(*) from audit.rejected_records where source_table = 'work_orders'"
    ).fetchone()[0]
    assert staged == in_mart + rejected


def test_occupancy_has_one_row_per_unit_per_month(con):
    units, months, rows = con.execute("""
        select count(distinct unit_id), count(distinct month_start), count(*)
        from marts.fct_unit_occupancy_monthly
    """).fetchone()
    assert rows == units * months
