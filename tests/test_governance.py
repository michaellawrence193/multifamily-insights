"""
Governance tests: personal data must not leak into the marts, which are the
tables analysts, dashboards and AI tools are allowed to read.
"""

import pytest

PII_COLUMNS = {"first_name", "last_name", "email", "phone", "date_of_birth", "annual_income"}


def mart_tables(con):
    return [row[0] for row in con.execute("""
        select table_name from information_schema.tables where table_schema = 'marts'
    """).fetchall()]


def test_marts_exist(con):
    assert len(mart_tables(con)) >= 6


def test_no_pii_columns_in_marts(con):
    leaks = con.execute(f"""
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'marts'
          and column_name in {tuple(PII_COLUMNS)}
    """).fetchall()
    assert leaks == [], f"PII found in marts: {leaks}"
