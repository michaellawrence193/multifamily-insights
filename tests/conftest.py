"""
Shared setup for all tests. pytest automatically loads this file and makes
each @pytest.fixture available to any test that names it as a parameter.
"""

import json
from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
ANSWER_KEY_PATH = PROJECT_ROOT / "data" / "raw" / "_planted_issues.json"


@pytest.fixture(scope="session")
def con():
    """One read-only connection to the warehouse, shared by every test."""
    if not DB_PATH.exists():
        pytest.exit("No warehouse found. Run generate_data.py, then build_models.py.")
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def answer_key():
    """The record IDs the generator deliberately corrupted."""
    return json.loads(ANSWER_KEY_PATH.read_text())


def ids(con, sql: str) -> set:
    """Run a query that returns one column of IDs, and return them as a set."""
    return {row[0] for row in con.execute(sql).fetchall()}
