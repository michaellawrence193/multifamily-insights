"""
generate_data.py
----------------
Creates a realistic (but fictional) multifamily apartment portfolio and saves
it as CSV files in data/raw/. These play the role of exports from a property
management system (like Yardi or RealPage) -- the "source system" data an
analytics engineer starts from.

Tables produced (and the GRAIN of each -- what one row represents):
    properties.csv   one row per apartment community
    units.csv        one row per apartment unit
    residents.csv    one row per resident (person)
    leases.csv       one row per lease (a resident renting a unit for a term)
    work_orders.csv  one row per maintenance request

Real source data is never clean, so we deliberately plant a few problems
(see plant_data_quality_issues). Phase 3's tests should catch every one.

Run it from the project root:
    python src/generate_data.py
"""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# A fixed "seed" makes the random data identical every run.
# That matters: tests and charts shouldn't change each time you regenerate.
SEED = 42
rng = np.random.default_rng(SEED)
fake = Faker()
Faker.seed(SEED)

# The data's "today". Leases ending after this date are still active.
AS_OF_DATE = date(2026, 10, 1)
HISTORY_START = date(2022, 1, 1)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


# ---------------------------------------------------------------------------
# 1. Properties
# ---------------------------------------------------------------------------
# Hand-written so the portfolio feels real: a mix of markets and building
# types, each with a typical rent level for that market.
PROPERTY_SEED_DATA = [
    # name,                     city,          state, type,       units, base_rent
    ("The Ashford",             "Charleston",  "SC",  "Garden",    120, 1650),
    ("Harbor Point Lofts",      "Charleston",  "SC",  "Mid-rise",   90, 1950),
    ("Cypress Commons",         "Atlanta",     "GA",  "Garden",    150, 1550),
    ("Midtown Collective",      "Atlanta",     "GA",  "High-rise", 140, 2200),
    ("Lakeline Residences",     "Austin",      "TX",  "Garden",    130, 1600),
    ("The Foundry",             "Austin",      "TX",  "Mid-rise",  100, 2050),
    ("Bellwood Park",           "Raleigh",     "NC",  "Garden",    110, 1500),
    ("Union Station Flats",     "Denver",      "CO",  "High-rise", 120, 2300),
]

def make_properties() -> pd.DataFrame:
    rows = []
    for i, (name, city, state, ptype, units, rent) in enumerate(PROPERTY_SEED_DATA, start=1):
        rows.append({
            "property_id": f"P{i:03d}",          # e.g. P001 -- the primary key
            "property_name": name,
            "city": city,
            "state": state,
            "property_type": ptype,
            "unit_count": units,
            "year_built": int(rng.integers(1995, 2024)),
            "market_base_rent": rent,            # used to price units below
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Units
# ---------------------------------------------------------------------------
# Bigger units cost more. These multipliers adjust a property's base rent.
FLOORPLANS = {
    # bedrooms: (share of units, sq ft range, rent multiplier)
    0: (0.10, (450, 600),   0.80),   # studio
    1: (0.45, (650, 850),   1.00),
    2: (0.35, (950, 1200),  1.35),
    3: (0.10, (1250, 1500), 1.70),
}

def make_units(properties: pd.DataFrame) -> pd.DataFrame:
    rows = []
    bedroom_options = list(FLOORPLANS.keys())
    bedroom_weights = [FLOORPLANS[b][0] for b in bedroom_options]

    for prop in properties.itertuples():
        for n in range(1, prop.unit_count + 1):
            beds = int(rng.choice(bedroom_options, p=bedroom_weights))
            _, (sq_min, sq_max), multiplier = FLOORPLANS[beds]
            floor = (n - 1) // 20 + 1   # ~20 units per floor
            rows.append({
                "unit_id": f"{prop.property_id}-{floor}{n:03d}",  # e.g. P001-1007
                "property_id": prop.property_id,                  # foreign key -> properties
                "unit_number": f"{floor}{n:03d}",
                "bedrooms": beds,
                "bathrooms": 1 if beds <= 1 else 2,
                "square_feet": int(rng.integers(sq_min, sq_max)),
                "floor": floor,
                # Asking rent today, with +/- 8% unit-to-unit variation
                "market_rent": round(prop.market_base_rent * multiplier * rng.uniform(0.92, 1.08), -1),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Leases + residents
# ---------------------------------------------------------------------------
# We simulate each unit's history month by month from 2022 to today:
# a resident moves in, the lease runs ~12 months, then they either RENEW
# (new lease, same resident, higher rent) or MOVE OUT (unit sits vacant,
# then a new resident moves in).
#
# The renewal decision isn't random noise -- it depends on factors a real
# property team cares about. That hidden logic is what Phase 4's
# machine-learning model will try to rediscover from the data alone.

def renewal_probability(rent_increase_pct: float, work_orders_in_term: int,
                        tenure_years: float, bedrooms: int) -> float:
    p = 0.58
    p -= rent_increase_pct * 2.5            # big rent bumps push people out
    p -= max(0, work_orders_in_term - 2) * 0.05   # lots of maintenance problems = unhappy
    p += min(tenure_years, 4) * 0.04        # long-time residents are "sticky"
    p += 0.04 if bedrooms >= 2 else 0       # families move less often
    return float(np.clip(p, 0.05, 0.95))


def new_resident(resident_rows: list, move_in: date) -> str:
    resident_id = f"R{len(resident_rows) + 1:05d}"
    first, last = fake.first_name(), fake.last_name()
    resident_rows.append({
        "resident_id": resident_id,
        "first_name": first,
        "last_name": last,
        "email": f"{first.lower()}.{last.lower()}{rng.integers(1, 99)}@example.com",
        "phone": fake.numerify("###-###-####"),
        "date_of_birth": fake.date_of_birth(minimum_age=21, maximum_age=70),
        "annual_income": int(np.clip(rng.normal(85000, 25000), 35000, 250000) // 1000 * 1000),
        "created_date": move_in,
    })
    return resident_id


def make_leases_and_residents(units: pd.DataFrame):
    lease_rows, resident_rows = [], []
    # How many maintenance requests each lease generated -- feeds both the
    # renewal decision and the work_orders table, so the two stay consistent.
    lease_work_order_counts = {}

    for unit in units.itertuples():
        # Start each unit partway into the history so leases are staggered
        current = HISTORY_START + timedelta(days=int(rng.integers(0, 365)))
        # Rents were lower back in 2022: start ~12% below today's market
        rent = unit.market_rent * 0.88
        resident_id = new_resident(resident_rows, current)
        tenure_start = current

        while current < AS_OF_DATE:
            term_months = int(rng.choice([6, 12, 12, 12, 12, 15]))
            end = current + timedelta(days=round(term_months * 30.4)) - timedelta(days=1)
            lease_id = f"L{len(lease_rows) + 1:06d}"

            # More bedrooms and older buildings = more things to break
            expected_wo = 1.2 + 0.3 * unit.bedrooms
            n_work_orders = int(rng.poisson(expected_wo))
            lease_work_order_counts[lease_id] = (unit.unit_id, current, min(end, AS_OF_DATE), n_work_orders)

            lease = {
                "lease_id": lease_id,
                "unit_id": unit.unit_id,                # foreign key -> units
                "resident_id": resident_id,             # foreign key -> residents
                "lease_start_date": current,
                "lease_end_date": end,
                "term_months": term_months,
                "monthly_rent": round(rent, 2),
                "security_deposit": round(rent * rng.choice([0.5, 1.0]), -1),
                "move_out_date": None,
                "lease_status": "Active" if end >= AS_OF_DATE else None,
                "is_renewal": bool(current != tenure_start),
            }
            lease_rows.append(lease)

            if end >= AS_OF_DATE:
                break  # this is the current, active lease

            # Lease has ended: does the resident renew?
            increase = float(np.clip(rng.normal(0.04, 0.025), -0.02, 0.12))
            tenure_years = (end - tenure_start).days / 365
            p_renew = renewal_probability(increase, n_work_orders, tenure_years, unit.bedrooms)

            if rng.random() < p_renew:
                lease["lease_status"] = "Renewed"
                rent *= 1 + increase
                current = end + timedelta(days=1)
            else:
                lease["lease_status"] = "Moved Out"
                lease["move_out_date"] = end
                # Vacant for 2-8 weeks while the unit is turned and re-leased
                current = end + timedelta(days=int(rng.integers(14, 60)))
                # New residents pay closer to market rent (market grows ~3%/yr)
                years_elapsed = (current - HISTORY_START).days / 365
                rent = unit.market_rent * 0.88 * (1.03 ** years_elapsed) * rng.uniform(0.96, 1.04)
                if current < AS_OF_DATE:
                    resident_id = new_resident(resident_rows, current)
                    tenure_start = current

    return pd.DataFrame(lease_rows), pd.DataFrame(resident_rows), lease_work_order_counts


# ---------------------------------------------------------------------------
# 4. Work orders
# ---------------------------------------------------------------------------
WORK_ORDER_CATEGORIES = {
    # category: (share, priority weights [Low, Medium, High, Emergency], avg days to close)
    "Plumbing":   (0.25, [0.2, 0.5, 0.2, 0.1], 2),
    "HVAC":       (0.20, [0.1, 0.4, 0.4, 0.1], 3),
    "Appliance":  (0.20, [0.3, 0.5, 0.2, 0.0], 4),
    "Electrical": (0.10, [0.2, 0.4, 0.3, 0.1], 2),
    "Pest":       (0.10, [0.3, 0.5, 0.2, 0.0], 5),
    "General":    (0.15, [0.6, 0.3, 0.1, 0.0], 6),
}
PRIORITIES = ["Low", "Medium", "High", "Emergency"]

def make_work_orders(lease_work_order_counts: dict) -> pd.DataFrame:
    rows = []
    categories = list(WORK_ORDER_CATEGORIES.keys())
    category_weights = [WORK_ORDER_CATEGORIES[c][0] for c in categories]

    for unit_id, start, end, n in lease_work_order_counts.values():
        span_days = max((end - start).days, 1)
        for _ in range(n):
            category = str(rng.choice(categories, p=category_weights))
            _, priority_weights, avg_days = WORK_ORDER_CATEGORIES[category]
            priority = str(rng.choice(PRIORITIES, p=priority_weights))
            opened = start + timedelta(days=int(rng.integers(0, span_days)))
            days_to_close = int(rng.exponential(avg_days / (3 if priority == "Emergency" else 1)))
            completed = opened + timedelta(days=days_to_close)
            is_open = completed > AS_OF_DATE
            rows.append({
                "work_order_id": None,  # assigned after sorting by date, below
                "unit_id": unit_id,     # foreign key -> units
                "category": category,
                "priority": priority,
                "opened_date": opened,
                "completed_date": None if is_open else completed,
                "status": "Open" if is_open else "Completed",
                "cost": round(float(rng.gamma(2, 90 if category != "HVAC" else 160)), 2),
            })

    df = pd.DataFrame(rows).sort_values("opened_date").reset_index(drop=True)
    df["work_order_id"] = [f"WO{i:06d}" for i in range(1, len(df) + 1)]
    return df


# ---------------------------------------------------------------------------
# 5. Plant data quality problems
# ---------------------------------------------------------------------------
# Every issue here mirrors something that really happens in property
# management data. Writing them down is how we'll check that Phase 3's
# tests catch all of them -- a "known answer" for our data quality suite.

def plant_data_quality_issues(properties, units, residents, leases, work_orders):
    issues = []        # human-readable summary
    answer_key = {}    # machine-readable: issue -> affected record IDs (used by tests)

    # (a) Duplicate rows: a lease exported twice (a classic sync/ETL bug)
    dupes = leases.sample(5, random_state=SEED)
    leases = pd.concat([leases, dupes], ignore_index=True)
    issues.append(f"5 duplicated lease rows: {sorted(dupes.lease_id)}")
    answer_key["duplicate_leases"] = sorted(dupes.lease_id)

    # (b) Orphan foreign key: leases pointing at a unit that doesn't exist
    #     (unit was deleted or renumbered in the source system)
    orphan_idx = leases.sample(3, random_state=SEED + 1).index
    leases.loc[orphan_idx, "unit_id"] = "P009-1001"
    issues.append(f"3 leases referencing non-existent unit P009-1001: {sorted(leases.loc[orphan_idx, 'lease_id'])}")
    answer_key["orphan_unit_leases"] = sorted(leases.loc[orphan_idx, "lease_id"])

    # (c) Impossible dates: lease ends before it starts (data-entry typo)
    bad_date_idx = leases.sample(4, random_state=SEED + 2).index
    leases.loc[bad_date_idx, "lease_end_date"] = (
        pd.to_datetime(leases.loc[bad_date_idx, "lease_start_date"]) - pd.Timedelta(days=30)
    ).dt.date
    issues.append(f"4 leases ending before they start: {sorted(leases.loc[bad_date_idx, 'lease_id'])}")
    answer_key["end_before_start_leases"] = sorted(leases.loc[bad_date_idx, "lease_id"])

    # (d) Invalid values: $0 and negative rents
    bad_rent_idx = leases.sample(3, random_state=SEED + 3).index
    leases.loc[bad_rent_idx, "monthly_rent"] = [0, -1450.00, 0]
    issues.append(f"3 leases with $0 or negative rent: {sorted(leases.loc[bad_rent_idx, 'lease_id'])}")
    answer_key["invalid_rent_leases"] = sorted(leases.loc[bad_rent_idx, "lease_id"])

    # (e) Missing values: resident emails never collected
    missing_email_idx = residents.sample(25, random_state=SEED + 4).index
    residents.loc[missing_email_idx, "email"] = None
    issues.append("25 residents with missing email")
    answer_key["missing_email_residents"] = sorted(residents.loc[missing_email_idx, "resident_id"])

    # (f) Inconsistent formatting: the same state written different ways
    properties.loc[properties.property_id == "P003", "state"] = "ga"
    properties.loc[properties.property_id == "P006", "state"] = "Texas"
    issues.append("2 properties with non-standard state codes ('ga', 'Texas')")
    answer_key["nonstandard_state_properties"] = ["P003", "P006"]

    # (g) Logically impossible: work order completed before it was opened
    wo_idx = work_orders[work_orders.status == "Completed"].sample(6, random_state=SEED + 5).index
    work_orders.loc[wo_idx, "completed_date"] = (
        pd.to_datetime(work_orders.loc[wo_idx, "opened_date"]) - pd.Timedelta(days=3)
    ).dt.date
    issues.append(f"6 work orders completed before opened: {sorted(work_orders.loc[wo_idx, 'work_order_id'])}")
    answer_key["completed_before_opened_work_orders"] = sorted(work_orders.loc[wo_idx, "work_order_id"])

    return properties, units, residents, leases, work_orders, issues, answer_key


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Generating portfolio data...")
    properties = make_properties()
    units = make_units(properties)
    leases, residents, wo_counts = make_leases_and_residents(units)
    work_orders = make_work_orders(wo_counts)

    properties, units, residents, leases, work_orders, issues, answer_key = plant_data_quality_issues(
        properties, units, residents, leases, work_orders
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tables = {
        "properties": properties,
        "units": units,
        "residents": residents,
        "leases": leases,
        "work_orders": work_orders,
    }
    for name, df in tables.items():
        df.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)
        print(f"  {name + '.csv':<18} {len(df):>6,} rows")

    # Save the answer key for Phase 3
    (OUTPUT_DIR / "_planted_issues.txt").write_text("\n".join(issues) + "\n")
    (OUTPUT_DIR / "_planted_issues.json").write_text(json.dumps(answer_key, indent=2))
    print(f"\nPlanted {len(issues)} data quality issues (see data/raw/_planted_issues.txt)")
    print(f"Data written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
