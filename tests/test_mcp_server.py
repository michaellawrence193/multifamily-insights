"""
Tests for the MCP server: the curated tools agree with the warehouse, and
the governance rules hold -- the AI can't see personal data, write data,
or read files, however it phrases its query.
"""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import mcp_server as server


# --- Governance ------------------------------------------------------------
@pytest.mark.parametrize("table", [
    "raw.residents", "staging.stg_residents", "raw.leases", "intermediate.int_leases_validated",
])
def test_ungoverned_layers_are_not_reachable(table):
    with pytest.raises(ToolError):
        server.run_sql(f"select * from {table}")


def test_no_pii_columns_reachable():
    pii = {"first_name", "last_name", "email", "phone", "date_of_birth", "annual_income"}
    result = server.run_sql("select column_name from information_schema.columns")
    reachable = {row[0] for row in result["rows"]}
    assert not reachable & pii


@pytest.mark.parametrize("sql", [
    "drop table marts.fct_leases",
    "delete from marts.fct_leases",
    "select 1; drop table marts.fct_leases",
    "attach 'data/warehouse.duckdb' as w",
])
def test_only_single_select_statements_allowed(sql):
    with pytest.raises(ToolError):
        server.run_sql(sql)


def test_cannot_read_files_from_disk():
    with pytest.raises(ToolError):
        server.run_sql("select * from read_csv('data/raw/residents.csv')")


def test_results_are_capped():
    result = server.run_sql("select * from marts.fct_unit_occupancy_monthly")
    assert result["row_count"] == server.MAX_ROWS
    assert result["truncated"] is True


# --- Curated tools agree with the warehouse --------------------------------
def test_list_tables_documents_grain():
    tables = {t["table"]: t for t in server.list_tables()}
    assert "marts.fct_leases" in tables
    assert "Grain" in tables["marts.fct_leases"]["description"]
    assert not any(name.startswith(("raw.", "staging.")) for name in tables)


def test_portfolio_summary_matches_sql(con):
    expected = con.execute("""
        select avg(is_occupied::int) from marts.fct_unit_occupancy_monthly
        where month_start = (select max(month_start) from marts.fct_unit_occupancy_monthly)
    """).fetchone()[0]
    assert server.portfolio_summary()["occupancy"] == pytest.approx(expected, abs=1e-4)


def test_property_names_are_case_insensitive():
    assert server.portfolio_summary("the ashford")["scope"] == "the ashford"


def test_unknown_property_lists_valid_names():
    with pytest.raises(ToolError, match="The Ashford"):
        server.portfolio_summary("Not A Real Place")


def test_higher_offer_means_fewer_expected_renewals():
    result = server.renewal_what_if(6)
    assert result["offer"]["expected_renewals"] < result["standard_4pct_offer"]["expected_renewals"]


def test_at_risk_leases_sorted_riskiest_first():
    rows = server.at_risk_leases(days_ahead=90, limit=20)
    risks = [r["p_renew"] for r in rows]
    assert 0 < len(rows) <= 20
    assert risks == sorted(risks)
