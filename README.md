# Multifamily Portfolio Insights

An end-to-end analytics engineering project for a fictional 8-property, 960-unit
apartment portfolio: from messy source-system data to tested data models, a
lease-renewal prediction model, and an interactive dashboard.

> **Status:** Phase 1 of 6 complete — source data generation.

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
| 2 | Model it into clean fact and dimension tables, with documented grain and keys | SQL, DuckDB | ⬜ |
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

## Getting started

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python src/generate_data.py
```

## How I built this

I built this project AI-first, using Claude as a pair programmer: it drafted
code, and I ran, reviewed, modified and tested every piece until I could
explain and defend each design decision.
