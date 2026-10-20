"""
build_models.py
---------------
Loads the raw CSVs into a DuckDB database and builds every SQL model, layer
by layer. This is a tiny version of what dbt does: each .sql file in models/
is just a SELECT, and this script wraps it in CREATE TABLE and runs the
files in dependency order.

Layers (each becomes a schema in the database):
    raw           CSVs loaded as-is. Never modified.
    staging       One cleaned model per source table: renamed, cast, deduplicated.
    intermediate  Business-rule checks that flag bad rows instead of dropping them.
    marts         Clean fact and dimension tables that dashboards and models use.
    audit         Every rejected record and the reason it was rejected.

Run it from the project root (after generate_data.py):
    python src/build_models.py
"""

from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
MODELS_DIR = PROJECT_ROOT / "models"
DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"

RAW_TABLES = ["properties", "units", "residents", "leases", "work_orders"]

# Build order matters: a model can only select from models built before it.
BUILD_ORDER = [
    "staging/stg_properties",
    "staging/stg_units",
    "staging/stg_residents",
    "staging/stg_leases",
    "staging/stg_work_orders",
    "intermediate/int_leases_validated",
    "intermediate/int_work_orders_validated",
    "marts/dim_properties",
    "marts/dim_units",
    "marts/dim_residents",
    "marts/fct_leases",
    "marts/fct_work_orders",
    "marts/fct_unit_occupancy_monthly",
    "audit/rejected_records",
]


def load_raw(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("create schema if not exists raw")
    for table in RAW_TABLES:
        csv_path = (RAW_DIR / f"{table}.csv").as_posix()
        # all_varchar: load every column as text, exactly as the source sent it.
        # Deciding types is staging's job, so bad values can't break the load.
        con.execute(f"""
            create or replace table raw.{table} as
            select * from read_csv('{csv_path}', header = true, all_varchar = true)
        """)


def build_model(con: duckdb.DuckDBPyConnection, model: str) -> int:
    schema, name = model.split("/")
    sql = (MODELS_DIR / f"{model}.sql").read_text()
    con.execute(f"create schema if not exists {schema}")
    con.execute(f"create or replace table {schema}.{name} as {sql}")
    return con.execute(f"select count(*) from {schema}.{name}").fetchone()[0]


def main():
    if not RAW_DIR.exists():
        raise SystemExit("No raw data found. Run: python src/generate_data.py")

    con = duckdb.connect(str(DB_PATH))
    print("Loading raw CSVs...")
    load_raw(con)

    print("Building models...")
    for model in BUILD_ORDER:
        rows = build_model(con, model)
        print(f"  {model:<42} {rows:>7,} rows")

    rejected = con.execute("""
        select source_table, dq_issue, count(*) as n
        from audit.rejected_records group by all order by all
    """).fetchall()
    print("\nRejected records (see audit.rejected_records):")
    for source, issue, n in rejected:
        print(f"  {source:<12} {issue:<36} {n}")

    con.close()
    print(f"\nWarehouse written to {DB_PATH}")


if __name__ == "__main__":
    main()
