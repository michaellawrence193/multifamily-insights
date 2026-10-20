"""
query.py -- run any SQL against the warehouse and print the result.

Examples (from the project root):
    python src/query.py "select * from marts.dim_properties"
    python src/query.py "select state_code, count(*) from marts.dim_units group by 1"
"""

import sys
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "warehouse.duckdb"

if len(sys.argv) < 2:
    raise SystemExit('Usage: python src/query.py "select ..."')

with duckdb.connect(str(DB_PATH), read_only=True) as con:
    con.sql(sys.argv[1]).show(max_rows=50, max_width=200)
