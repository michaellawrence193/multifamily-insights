# Multifamily Portfolio Insights

An end-to-end analytics engineering project for a fictional 8-property, 960-unit
apartment portfolio: from messy source-system data to tested data models, a
lease-renewal prediction model, and an interactive dashboard.

> **Status:** Phase 2 of 6 complete — source data and SQL data models.

## Why this project

Property management companies run on data from leasing, maintenance and
accounting systems. That data arrives messy, and the decisions built on it
(pricing a renewal, staffing maintenance, forecasting occupancy) are only as
good as the data underneath. This project walks through the full lifecycle
an analytics engineer owns: **source data → modeling → data quality →
prediction → a product people use to decide.**

## Roadmap

| Phase | What | Tools | Status |
|---|---|---|---|
| 1 | Generate realistic source data, with planted data quality issues | Python, pandas, Faker | ✅ |
| 2 | Model it into clean fact and dimension tables, with documented grain and keys | SQL, DuckDB | ✅ |
| 3 | Automated data quality tests that catch every planted issue | pytest | ⬜ |
| 4 | Predict which residents are at risk of not renewing | scikit-learn | ⬜ |
| 5 | Interactive dashboard: occupancy, rent trends, renewal risk | Streamlit | ⬜ |
| 6 | Let an AI assistant query the portfolio through an MCP server | MCP | ⬜ |

## The source data

`src/generate_data.py` simulates each unit's history from January 2022 to
October 2026. Residents sign leases, then either renew (at a higher rent) or
move out (the unit sits vacant, then re-leases). Renewal decisions follow
realistic drivers — size of the rent increase, number of maintenance problems,
how long the resident has lived there — which Phase 4 will try to rediscover.

| Table | Grain (one row = …) | Primary key | Foreign keys |
|---|---|---|---|
| `properties` | an apartment community | `property_id` | — |
| `units` | an apartment unit | `unit_id` | `property_id` |
| `residents` | a resident | `resident_id` | — |
| `leases` | a lease term for one resident in one unit | `lease_id` | `unit_id`, `resident_id` |
| `work_orders` | a maintenance request | `work_order_id` | `unit_id` |

### Planted data quality issues

Real source data is never clean, so the generator deliberately introduces seven
kinds of problems: duplicate rows, orphaned foreign keys, impossible dates,
invalid rents, missing values, inconsistent state codes, and work orders
completed before they were opened. The full list is written to
`data/raw/_planted_issues.txt` as an answer key for Phase 3's tests.

## The data model

`src/build_models.py` loads the raw CSVs into a local DuckDB warehouse and builds
SQL models in layers, the same pattern dbt uses. Each `.sql` file in `models/`
is a plain `SELECT` with its grain documented at the top.

```
raw  ──►  staging  ──►  intermediate  ──►  marts
                              │
                              └──►  audit
```

| Layer | Purpose |
|---|---|
| `raw` | CSVs loaded exactly as received, every column as text. Never modified. |
| `staging` | One model per source table: types cast, values standardized, duplicates removed. |
| `intermediate` | Business-rule checks. Bad rows are **flagged with a reason**, not silently dropped. |
| `marts` | Clean tables for dashboards and models. |
| `audit` | Every rejected record and why — a worklist for source-system owners. |

### Marts

| Table | Grain (one row = …) | Notes |
|---|---|---|
| `dim_properties` | a property | State codes standardized |
| `dim_units` | a unit | Property attributes denormalized for easy filtering |
| `dim_residents` | a resident | **No PII** — age and income bands only |
| `fct_leases` | a lease term | Valid leases only; includes rent change vs. prior lease |
| `fct_work_orders` | a maintenance request | Includes days to complete |
| `fct_unit_occupancy_monthly` | a unit in a month | Month-end occupancy and rent |

**Known limitations:** occupancy history starts January 2023, because units'
first leases are staggered through 2022. Leases rejected by validation can make
a unit look vacant for months it was really occupied.

## Getting started

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python src/generate_data.py      # 1. create the raw source data
python src/build_models.py       # 2. build the warehouse

# Explore with any SQL query:
python src/query.py "select * from marts.dim_properties"
```

## How I built this

I built this project AI-first, using Claude as a pair programmer: it drafted
code, and I ran, reviewed, modified and tested every piece until I could
explain and defend each design decision.
