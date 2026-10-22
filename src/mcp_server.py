"""
mcp_server.py
-------------
An MCP (Model Context Protocol) server that lets an AI assistant such as
Claude answer questions about the portfolio, like:
    "Which property has the lowest occupancy?"
    "What happens to renewals if we offer 6% instead of 4%?"
    "Which leases ending this quarter are most at risk?"

MCP is an open standard for connecting AI assistants to tools and data. This
file defines the tools; the assistant decides when to call them.

Two design choices make the data reliable and safe for an AI to use:

1. CURATED METRICS. portfolio_summary, renewal_what_if and at_risk_leases
   compute key numbers one fixed way, with definitions included in the
   result. The AI doesn't invent its own formula for "occupancy" each time,
   so its answers match the dashboard.

2. GOVERNED ACCESS. For open-ended questions, run_sql lets the AI write
   queries -- but only against a copy of the governed tables (marts, ml,
   audit) held in memory. The raw and staging layers, which contain resident
   names, emails, phone numbers and birth dates, are never copied in, so the
   AI cannot see personal data even if it tries.

Run the pipeline first (generate_data, build_models, train_model), then
connect this server to Claude Desktop -- see the README.
"""

import re
import sys
from pathlib import Path

import duckdb
import joblib
import pandas as pd
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_model  # noqa: E402  (shares the model's feature list)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
MODEL_PATH = PROJECT_ROOT / "artifacts" / "renewal_model.joblib"
MODELS_DIR = PROJECT_ROOT / "models"

ALLOWED_SCHEMAS = ["marts", "ml", "audit"]
MAX_ROWS = 200
STANDARD_OFFER = 0.04

mcp = MCPServer(
    "multifamily-portfolio",
    instructions=(
        "Data for a fictional 8-property, 960-unit apartment portfolio, as of October 1, 2026. "
        "Prefer portfolio_summary, renewal_what_if and at_risk_leases for standard metrics; "
        "use list_tables and run_sql for anything else. State the definitions and caveats "
        "the tools return when you report numbers."
    ),
)


# ---------------------------------------------------------------------------
# Governed, in-memory copy of the warehouse
# ---------------------------------------------------------------------------
def build_governed_db() -> duckdb.DuckDBPyConnection:
    """Copy only the allowed schemas into a fresh in-memory database, then lock it down."""
    if not DB_PATH.exists():
        raise RuntimeError(
            "Warehouse not found. Run generate_data.py, build_models.py and train_model.py first."
        )
    con = duckdb.connect(":memory:")
    con.execute(f"attach '{DB_PATH.as_posix()}' as warehouse (read_only)")
    tables = con.execute(f"""
        select table_schema, table_name from information_schema.tables
        where table_catalog = 'warehouse' and table_schema in {tuple(ALLOWED_SCHEMAS)}
        order by 1, 2
    """).fetchall()
    for schema, table in tables:
        con.execute(f"create schema if not exists {schema}")
        con.execute(f"create table {schema}.{table} as select * from warehouse.{schema}.{table}")
    con.execute("detach warehouse")
    # No reading files, no attaching other databases, and these settings can't be undone.
    con.execute("set enable_external_access = false")
    con.execute("set lock_configuration = true")
    return con


DB = build_governed_db()


def query_df(sql: str, params: list | None = None) -> pd.DataFrame:
    return DB.cursor().execute(sql, params or []).df()


def resolve_property(property_name: str | None) -> str | None:
    """Turn a property name (any capitalization) into its ID; None means all properties."""
    if not property_name:
        return None
    match = query_df(
        "select property_id from marts.dim_properties where lower(property_name) = lower(?)",
        [property_name.strip()],
    )
    if match.empty:
        names = ", ".join(query_df("select property_name from marts.dim_properties order by 1").property_name)
        raise ToolError(f"Unknown property '{property_name}'. Valid names: {names}")
    return match.property_id[0]


def property_filter(property_id: str | None, column: str = "property_id") -> tuple[str, list]:
    return (f"and {column} = ?", [property_id]) if property_id else ("", [])


def table_description(schema: str, table: str) -> str:
    """Reuse the documentation at the top of each SQL model file."""
    sql_file = MODELS_DIR / schema / f"{table}.sql"
    if not sql_file.exists():
        if table == "renewal_risk_scores":
            return "Grain: one row per active lease. Renewal probability from the model, assuming a 4% offer."
        return ""
    comments = []
    for line in sql_file.read_text().splitlines():
        if not line.startswith("--"):
            break
        comments.append(line.lstrip("- ").strip())
    return " ".join(c for c in comments if c)


# ---------------------------------------------------------------------------
# Tools for open-ended questions
# ---------------------------------------------------------------------------
@mcp.tool()
def list_tables() -> list[dict]:
    """List the tables available to run_sql, with each table's grain, description and columns.
    Call this before writing SQL."""
    tables = query_df("""
        select table_schema, table_name from information_schema.tables
        where table_schema not in ('information_schema', 'pg_catalog', 'main')
        order by 1, 2
    """)
    result = []
    for row in tables.itertuples():
        columns = query_df(
            """select column_name, data_type from information_schema.columns
               where table_schema = ? and table_name = ? order by ordinal_position""",
            [row.table_schema, row.table_name],
        )
        result.append({
            "table": f"{row.table_schema}.{row.table_name}",
            "description": table_description(row.table_schema, row.table_name),
            "columns": dict(zip(columns.column_name, columns.data_type)),
        })
    return result


@mcp.tool()
def run_sql(sql: str) -> dict:
    """Run one read-only SQL query (DuckDB dialect) against the governed tables and return up
    to 200 rows. Only SELECT or WITH queries are allowed. Use list_tables to see what exists.
    Resident personal data is not available."""
    statement = sql.strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", statement, re.IGNORECASE):
        raise ToolError("Only a single SELECT (or WITH ... SELECT) query is allowed.")
    if ";" in statement:
        raise ToolError("Only one statement per call is allowed.")
    try:
        cursor = DB.cursor()
        cursor.execute(statement)
        columns = [c[0] for c in cursor.description]
        rows = cursor.fetchmany(MAX_ROWS + 1)
    except duckdb.Error as e:
        raise ToolError(f"Query failed: {e}") from e
    truncated = len(rows) > MAX_ROWS
    return {
        "columns": columns,
        "rows": [[str(v) if v is not None else None for v in r] for r in rows[:MAX_ROWS]],
        "row_count": min(len(rows), MAX_ROWS),
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Curated tools: standard metrics, computed one consistent way
# ---------------------------------------------------------------------------
@mcp.tool()
def portfolio_summary(property_name: str | None = None) -> dict:
    """Headline metrics for the whole portfolio, or for one property by name:
    occupancy, average rent (both with year-over-year change), 12-month renewal rate,
    and open work orders."""
    pid = resolve_property(property_name)
    where, params = property_filter(pid)
    monthly = query_df(f"""
        select month_start, avg(is_occupied::int) as occupancy, avg(monthly_rent) as avg_rent
        from marts.fct_unit_occupancy_monthly where 1=1 {where}
        group by 1 order by 1
    """, params)
    latest, year_ago = monthly.iloc[-1], monthly.iloc[-13]
    renewal_rate = query_df(f"""
        select avg(case when lease_status = 'Renewed' then 1.0 else 0 end) as rate
        from marts.fct_leases
        where lease_status in ('Renewed', 'Moved Out') and lease_end_date >= date '2025-10-01' {where}
    """, params).rate[0]
    open_work_orders = query_df(
        f"select count(*) as n from marts.fct_work_orders where status = 'Open' {where}", params
    ).n[0]
    return {
        "scope": property_name or "All properties",
        "month": str(latest.month_start.date()),
        "occupancy": round(float(latest.occupancy), 4),
        "occupancy_change_vs_last_year_pts": round(float(latest.occupancy - year_ago.occupancy) * 100, 1),
        "average_rent": round(float(latest.avg_rent), 2),
        "average_rent_change_vs_last_year": round(float(latest.avg_rent / year_ago.avg_rent - 1), 4),
        "renewal_rate_last_12_months": round(float(renewal_rate), 4),
        "open_work_orders": int(open_work_orders),
        "definitions": {
            "occupancy": "Share of units with a lease covering the last day of the month.",
            "average_rent": "Average scheduled monthly rent of occupied units (not collections).",
            "renewal_rate": "Renewed / (Renewed + Moved Out) for leases ending in the last 12 months.",
        },
    }


@mcp.tool()
def renewal_what_if(offer_pct: float, property_name: str | None = None) -> dict:
    """Estimate how many active residents would renew if every one were offered the given rent
    increase (offer_pct as a percent, e.g. 6 for 6%), compared with the standard 4% offer.
    Optionally limit to one property by name."""
    if not -5 <= offer_pct <= 20:
        raise ToolError("offer_pct should be a percent between -5 and 20, e.g. 6 for 6%.")
    pid = resolve_property(property_name)
    where, params = property_filter(pid)
    features = query_df(f"select * from ml.lease_renewal_features where renewed is null {where}", params)
    model = joblib.load(MODEL_PATH)
    inputs = train_model.NUMERIC_FEATURES + train_model.CATEGORICAL_FEATURES
    rent = features.monthly_rent.astype(float)

    def scenario(offer: float) -> dict:
        p = model.predict_proba(features.assign(renewal_offer_pct=offer)[inputs])[:, 1]
        return {
            "expected_renewals": round(float(p.sum()), 1),
            "expected_move_outs": round(float(len(p) - p.sum()), 1),
            "monthly_rent_from_renewals": round(float((p * rent * (1 + offer)).sum()), 0),
        }

    return {
        "scope": property_name or "All properties",
        "active_leases": len(features),
        "offer": scenario(offer_pct / 100),
        "standard_4pct_offer": scenario(STANDARD_OFFER),
        "caveats": [
            "Expected counts are sums of each resident's renewal probability, not a list of people.",
            "Rent excludes new residents who re-lease vacated units and turnover costs.",
            "The model (test AUC ~0.60) shows association, not proof that the offer causes move-outs.",
        ],
    }


@mcp.tool()
def at_risk_leases(days_ahead: int = 90, limit: int = 10, property_name: str | None = None) -> list[dict]:
    """Active leases ending within the next days_ahead days, riskiest first, assuming the
    standard 4% renewal offer. Optionally limit to one property by name."""
    pid = resolve_property(property_name)
    where, params = property_filter(pid, "s.property_id")
    rows = query_df(f"""
        select p.property_name, s.unit_id, s.lease_end_date, s.monthly_rent,
               s.tenure_months, s.work_order_count, s.p_renew, s.risk_tier
        from ml.renewal_risk_scores s
        join marts.dim_properties p using (property_id)
        where s.lease_end_date < date '2026-10-01' + to_days(?) {where}
        order by s.p_renew
        limit ?
    """, [int(days_ahead)] + params + [int(min(limit, 100))])
    rows["lease_end_date"] = rows.lease_end_date.astype(str)
    rows["monthly_rent"] = rows.monthly_rent.astype(float)
    return rows.to_dict(orient="records")


if __name__ == "__main__":
    mcp.run()
