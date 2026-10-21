"""
dashboard.py
------------
An interactive dashboard for the portfolio: occupancy and rent trends,
renewal risk with a what-if slider for renewal offers, and a data quality view.

Run from the project root:
    streamlit run src/dashboard.py

If the warehouse doesn't exist yet (for example, on a fresh deploy to
Streamlit Community Cloud), the app builds it first by running the whole
pipeline: generate -> build models -> train. Reproducible data makes that
possible: the same seed gives the same portfolio everywhere.
"""

from pathlib import Path

import altair as alt
import duckdb
import joblib
import pandas as pd
import streamlit as st

import build_models
import generate_data
import train_model

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
MODEL_PATH = PROJECT_ROOT / "artifacts" / "renewal_model.joblib"
AS_OF = pd.Timestamp("2026-10-01")

# Chart colors (validated palette: one blue for single-series charts, and
# reserved status colors for risk tiers -- always shown with a text label).
BLUE = "#2a78d6"
RISK_COLORS = {"High": "#d03b3b", "Medium": "#ec835a", "Low": "#0ca30c"}

st.set_page_config(page_title="Portfolio Insights", page_icon="🏢", layout="wide")


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="First run: building the warehouse and training the model...")
def ensure_pipeline() -> bool:
    """Build everything once if it's missing."""
    if not DB_PATH.exists() or not MODEL_PATH.exists():
        generate_data.main()
        build_models.main()
        train_model.main()
    return True


@st.cache_data
def query(sql: str) -> pd.DataFrame:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(sql).df()


@st.cache_resource
def load_model():
    return joblib.load(MODEL_PATH)


def in_list(values) -> str:
    """Turn a list of IDs into a SQL list: ('P001', 'P002')."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def line_chart(df, x, y, y_title, y_format, y_domain=None):
    scale = alt.Scale(domain=y_domain) if y_domain else alt.Scale(zero=False)
    base = alt.Chart(df).encode(x=alt.X(f"{x}:T", title=None))
    line = base.mark_line(color=BLUE, strokeWidth=2).encode(
        y=alt.Y(f"{y}:Q", title=y_title, scale=scale, axis=alt.Axis(format=y_format))
    )
    # Invisible wide points make hovering easy; tooltip shows the exact value
    hover = base.mark_point(size=150, opacity=0).encode(
        y=f"{y}:Q",
        tooltip=[alt.Tooltip(f"{x}:T", title="Month", format="%b %Y"),
                 alt.Tooltip(f"{y}:Q", title=y_title, format=y_format)],
    )
    return (line + hover).properties(height=260)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
ensure_pipeline()

properties = query("select property_id, property_name, city, state_code from marts.dim_properties order by 1")

st.title("Multifamily Portfolio Insights")
st.caption(f"Fictional 8-property, 960-unit portfolio · data as of {AS_OF:%B} {AS_OF.day}, {AS_OF.year}")

picked = st.multiselect(
    "Properties",
    options=properties.property_id,
    default=list(properties.property_id),
    format_func=lambda pid: properties.set_index("property_id").property_name[pid],
)
if not picked:
    st.info("Select at least one property.")
    st.stop()
selected = in_list(picked)

tab_overview, tab_risk, tab_quality = st.tabs(["Portfolio overview", "Renewal risk", "Data quality"])

# ---------------------------------------------------------------------------
# Tab 1: Portfolio overview
# ---------------------------------------------------------------------------
with tab_overview:
    monthly = query(f"""
        select month_start,
               avg(is_occupied::int)                   as occupancy,
               avg(monthly_rent)                       as avg_rent
        from marts.fct_unit_occupancy_monthly
        where property_id in {selected}
        group by 1 order by 1
    """)
    latest, year_ago = monthly.iloc[-1], monthly.iloc[-13]

    renewals = query(f"""
        select avg(case when lease_status = 'Renewed' then 1.0 else 0 end) as rate
        from marts.fct_leases
        where property_id in {selected}
          and lease_status in ('Renewed', 'Moved Out')
          and lease_end_date >= date '2025-10-01'
    """).rate[0]
    open_wo = query(f"""
        select count(*) as n from marts.fct_work_orders
        where property_id in {selected} and status = 'Open'
    """).n[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Occupancy", f"{latest.occupancy:.1%}",
              f"{(latest.occupancy - year_ago.occupancy) * 100:+.1f} pts vs. last year")
    c2.metric("Average rent", f"${latest.avg_rent:,.0f}",
              f"{latest.avg_rent / year_ago.avg_rent - 1:+.1%} vs. last year")
    c3.metric("Renewal rate (last 12 months)", f"{renewals:.1%}")
    c4.metric("Open work orders", f"{open_wo:,}")

    left, right = st.columns(2)
    with left:
        st.subheader("Occupancy, month-end")
        st.altair_chart(line_chart(monthly, "month_start", "occupancy", "Occupancy", ".0%",
                                   y_domain=[0.85, 1.0]), use_container_width=True)
    with right:
        st.subheader("Average rent, occupied units")
        st.altair_chart(line_chart(monthly, "month_start", "avg_rent", "Average rent", "$,.0f"),
                        use_container_width=True)

    st.subheader("By property, latest month")
    by_property = query(f"""
        select p.property_name, p.city,
               avg(o.is_occupied::int)    as occupancy,
               avg(o.monthly_rent)        as avg_rent,
               count(*)                   as units
        from marts.fct_unit_occupancy_monthly o
        join marts.dim_properties p using (property_id)
        where o.property_id in {selected}
          and o.month_start = (select max(month_start) from marts.fct_unit_occupancy_monthly)
        group by all order by occupancy
    """)
    st.dataframe(
        by_property,
        hide_index=True,
        use_container_width=True,
        column_config={
            "property_name": "Property",
            "city": "City",
            "occupancy": st.column_config.ProgressColumn("Occupancy", format="percent",
                                                         min_value=0.8, max_value=1.0),
            "avg_rent": st.column_config.NumberColumn("Average rent", format="dollar"),
            "units": "Units",
        },
    )
    st.caption("Occupancy history starts January 2023; units' first leases were staggered through 2022.")

# ---------------------------------------------------------------------------
# Tab 2: Renewal risk
# ---------------------------------------------------------------------------
with tab_risk:
    st.markdown(
        "Every active lease is scored by a model trained on past renewals. "
        "Use the slider to see how the **size of the renewal offer** changes expected renewals."
    )

    features = query(f"""
        select f.*, p.property_name
        from ml.lease_renewal_features f
        join marts.dim_properties p using (property_id)
        where f.renewed is null and f.property_id in {selected}
    """)
    model = load_model()
    model_inputs = train_model.NUMERIC_FEATURES + train_model.CATEGORICAL_FEATURES

    def score(offer: float) -> pd.Series:
        scenario = features.assign(renewal_offer_pct=offer)
        return pd.Series(model.predict_proba(scenario[model_inputs])[:, 1], index=features.index)

    offer_pct = st.slider("Renewal increase offered to every resident (%)", 0.0, 10.0, 4.0, 0.5,
                          help="4% is the portfolio's typical offer.")
    offer = offer_pct / 100

    p_now, p_standard = score(offer), score(0.04)
    features["p_renew"] = p_now
    features["risk_tier"] = pd.cut(p_now, bins=[0, 0.45, 0.6, 1],
                                   labels=["High", "Medium", "Low"], include_lowest=True).astype(str)

    expected_renewals = p_now.sum()
    retained_rent = (p_now * features.monthly_rent.astype(float) * (1 + offer)).sum()
    standard_rent = (p_standard * features.monthly_rent.astype(float) * 1.04).sum()

    # Compare against the typical 4% offer (no comparison shown when the slider is at 4%)
    at_standard = offer_pct == 4.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Expected renewals", f"{expected_renewals:,.0f} of {len(features):,}",
              None if at_standard else f"{expected_renewals - p_standard.sum():+.0f} vs. 4% offer")
    c2.metric("Expected move-outs", f"{len(features) - expected_renewals:,.0f}",
              None if at_standard else f"{p_standard.sum() - expected_renewals:+.0f} vs. 4% offer",
              delta_color="inverse")
    c3.metric("Monthly rent from renewing residents", f"${retained_rent:,.0f}",
              None if at_standard else f"{retained_rent - standard_rent:+,.0f} vs. 4% offer")
    st.caption(
        "Rent shown is only from residents expected to renew. It excludes rent from new residents "
        "and turnover costs (vacancy, cleaning, marketing), which a real pricing decision must weigh. "
        "The model shows association, not proof of cause: confirming the offer's effect would take "
        "a controlled test."
    )

    left, right = st.columns([1, 2])
    with left:
        st.subheader("Residents by risk tier")
        tiers = (features.risk_tier.value_counts()
                 .reindex(["High", "Medium", "Low"], fill_value=0)
                 .rename_axis("tier").reset_index(name="residents"))
        bars = alt.Chart(tiers).mark_bar(cornerRadiusEnd=4, size=28).encode(
            y=alt.Y("tier:N", sort=["High", "Medium", "Low"], title=None),
            x=alt.X("residents:Q", title="Residents"),
            color=alt.Color("tier:N", scale=alt.Scale(domain=list(RISK_COLORS),
                                                      range=list(RISK_COLORS.values())), legend=None),
            tooltip=[alt.Tooltip("tier:N", title="Risk tier"), alt.Tooltip("residents:Q", title="Residents")],
        )
        labels = bars.mark_text(align="left", dx=4).encode(text="residents:Q", color=alt.value("gray"))
        st.altair_chart((bars + labels).properties(height=180), use_container_width=True)
        st.caption("High: under 45% likely to renew · Medium: 45–60% · Low: over 60%")

    with right:
        st.subheader("Leases ending in the next 90 days, highest risk first")
        upcoming = (features[features.lease_end_date < AS_OF + pd.Timedelta(days=90)]
                    .sort_values("p_renew")
                    [["property_name", "unit_id", "lease_end_date", "monthly_rent",
                      "tenure_months", "work_order_count", "p_renew"]])
        st.dataframe(
            upcoming,
            hide_index=True,
            use_container_width=True,
            height=320,
            column_config={
                "property_name": "Property",
                "unit_id": "Unit",
                "lease_end_date": st.column_config.DateColumn("Lease ends", format="MMM D, YYYY"),
                "monthly_rent": st.column_config.NumberColumn("Current rent", format="dollar"),
                "tenure_months": "Months in unit",
                "work_order_count": "Work orders",
                "p_renew": st.column_config.ProgressColumn("Chance of renewing", format="percent",
                                                           min_value=0, max_value=1),
            },
        )

# ---------------------------------------------------------------------------
# Tab 3: Data quality
# ---------------------------------------------------------------------------
with tab_quality:
    st.markdown(
        "Source data is checked on every build. Records that fail a business rule are "
        "**quarantined with a reason** rather than silently dropped, so the source-system "
        "owner has a worklist to fix."
    )
    counts = query("""
        select
            (select count(*) from raw.leases)           as raw_leases,
            (select count(*) from staging.stg_leases)   as staged_leases,
            (select count(*) from marts.fct_leases)     as mart_leases,
            (select count(*) from audit.rejected_records where source_table = 'leases') as rejected_leases
    """).iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Leases received", f"{counts.raw_leases:,}")
    c2.metric("Duplicates removed", f"{counts.raw_leases - counts.staged_leases:,}")
    c3.metric("Quarantined", f"{counts.rejected_leases:,}")
    c4.metric("Used in reporting", f"{counts.mart_leases:,}")

    st.subheader("Quarantined records")
    st.dataframe(
        query("select * from audit.rejected_records order by source_table, dq_issue, record_id"),
        hide_index=True,
        use_container_width=True,
        column_config={"source_table": "Table", "record_id": "Record", "dq_issue": "Reason"},
    )

    st.subheader("Known limitations")
    st.markdown(
        "- **Occupancy is a month-end snapshot.** A unit occupied for most of a month but vacant on "
        "the last day counts as vacant.\n"
        "- **Rent figures are scheduled rent, not collections.** There is no payments data.\n"
        "- **Quarantined leases are excluded,** so their units may show as vacant for those months.\n"
        "- **Renewal predictions are modest** (test AUC ≈ 0.60). Use them to prioritize outreach, "
        "not to predict any one resident."
    )
