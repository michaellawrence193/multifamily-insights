"""
train_model.py
--------------
Trains a model that predicts whether a resident will renew their lease, then
scores every active lease so the property team knows who is at risk.

Business question: "Which residents are likely to move out, and what drives it?"
Every move-out costs a property weeks of lost rent plus turnover costs
(cleaning, paint, marketing), so knowing who is at risk early lets the team act.

Steps:
    1. Load features from the warehouse (ml.lease_renewal_features)
    2. Split by TIME: train on older leases, test on newer ones
    3. Baseline: how good is a "model" that always guesses the most common answer?
    4. Leakage demo: a feature that looks great but cheats
    5. Train two honest models and compare them
    6. Explain the drivers (what the business actually wants to know)
    7. Score active leases and save the results for the dashboard

Run from the project root (after build_models.py):
    python src/train_model.py
"""

from pathlib import Path

import duckdb
import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "warehouse.duckdb"
MODEL_PATH = PROJECT_ROOT / "artifacts" / "renewal_model.joblib"

# Leases ending before this date train the model; leases ending after test it.
TEST_START_DATE = pd.Timestamp("2025-07-01")

# Active leases haven't received a renewal offer yet in our data. We score them
# assuming a standard offer. (The dashboard in Phase 5 will let users change it.)
ASSUMED_OFFER_PCT = 0.04

NUMERIC_FEATURES = [
    "term_months",
    "monthly_rent",
    "renewal_offer_pct",
    "tenure_months",
    "work_order_count",
    "urgent_work_order_count",
    "avg_days_to_complete",
    "bedrooms",
    "square_feet",
]
CATEGORICAL_FEATURES = ["age_band", "income_band"]
LABEL = "renewed"


def load_features(con) -> pd.DataFrame:
    df = con.execute("select * from ml.lease_renewal_features").df()
    df["lease_end_date"] = pd.to_datetime(df["lease_end_date"])
    df["renewal_offer_pct"] = df["renewal_offer_pct"].astype(float)
    return df


def split_by_time(labeled: pd.DataFrame):
    """
    Why not a random split? Because in real life we always predict the FUTURE
    from the PAST. A random split lets the model peek at 2026 leases while
    learning, which makes test scores look better than they'll be in practice.
    """
    train = labeled[labeled.lease_end_date < TEST_START_DATE]
    test = labeled[labeled.lease_end_date >= TEST_START_DATE]
    return train, test


def make_pipeline(model, numeric, categorical) -> Pipeline:
    """
    A Pipeline bundles data preparation with the model, so exactly the same
    steps run during training and when scoring new leases.
      - StandardScaler puts numbers on the same scale (rent in $1000s and
        work orders in single digits become comparable).
      - OneHotEncoder turns categories like city into 0/1 columns.
    """
    prep = ColumnTransformer([
        ("num", StandardScaler(), numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
    ])
    return Pipeline([("prep", prep), ("model", model)])


def evaluate(name, pipeline, train, test, numeric, categorical) -> float:
    features = numeric + categorical
    pipeline.fit(train[features], train[LABEL])
    p_renew = pipeline.predict_proba(test[features])[:, 1]
    auc = roc_auc_score(test[LABEL], p_renew)
    acc = accuracy_score(test[LABEL], p_renew >= 0.5)
    print(f"  {name:<34} AUC {auc:.3f}   accuracy {acc:.1%}")
    return auc


def add_leaky_feature(df: pd.DataFrame) -> pd.DataFrame:
    """
    DELIBERATELY WRONG -- used only to demonstrate data leakage.

    'Rent change on the resident's next lease' sounds harmless, but a next
    lease only exists if the resident RENEWED. Anyone who moved out gets 0.
    The feature secretly contains the answer.
    """
    df = df.sort_values(["unit_id", "resident_id", "lease_start_date"]).copy()
    next_rent = df.groupby(["unit_id", "resident_id"])["monthly_rent"].shift(-1)
    df["next_lease_rent_change_pct"] = (next_rent / df["monthly_rent"] - 1).astype(float).fillna(0)
    return df


def main():
    con = duckdb.connect(str(DB_PATH))
    df = load_features(con)
    labeled = df[df[LABEL].notna()].copy()
    labeled[LABEL] = labeled[LABEL].astype(int)
    active = df[df[LABEL].isna()].copy()

    train, test = split_by_time(labeled)
    print(f"Training on {len(train):,} leases ending before {TEST_START_DATE.date()}")
    print(f"Testing on  {len(test):,} leases ending after\n")

    # --- Step 3: baseline -------------------------------------------------
    # Always guessing the most common outcome. Any real model must beat this.
    majority = int(train[LABEL].mean() >= 0.5)
    print("1. Baseline")
    print(f"  {'Always guess the most common outcome':<34} AUC 0.500   "
          f"accuracy {accuracy_score(test[LABEL], [majority] * len(test)):.1%}")

    # --- Step 4: leakage demo ---------------------------------------------
    print("\n2. Leakage demo (DO NOT USE)")
    # Built from ALL leases: a renewal's next lease may still be active.
    leaky = add_leaky_feature(df)
    leaky = leaky[leaky[LABEL].notna()].astype({LABEL: int})
    leaky_train, leaky_test = split_by_time(leaky)
    evaluate("With next-lease rent change", make_pipeline(LogisticRegression(max_iter=1000),
             NUMERIC_FEATURES + ["next_lease_rent_change_pct"], CATEGORICAL_FEATURES),
             leaky_train, leaky_test, NUMERIC_FEATURES + ["next_lease_rent_change_pct"],
             CATEGORICAL_FEATURES)
    print("  ^ Too good to be true. The feature only exists AFTER the decision.")

    # --- Step 5: honest models --------------------------------------------
    print("\n3. Honest models")
    logistic = make_pipeline(LogisticRegression(max_iter=1000), NUMERIC_FEATURES, CATEGORICAL_FEATURES)
    boosted = make_pipeline(HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, random_state=42),
                            NUMERIC_FEATURES, CATEGORICAL_FEATURES)
    auc_logistic = evaluate("Logistic regression", logistic, train, test,
                            NUMERIC_FEATURES, CATEGORICAL_FEATURES)
    auc_boosted = evaluate("Gradient boosting", boosted, train, test,
                           NUMERIC_FEATURES, CATEGORICAL_FEATURES)

    # Prefer the simpler, explainable model unless the complex one is clearly better.
    chosen = boosted if auc_boosted > auc_logistic + 0.02 else logistic
    chosen_name = "gradient boosting" if chosen is boosted else "logistic regression"
    print(f"  -> Using {chosen_name}")

    # --- Step 6: drivers --------------------------------------------------
    # Logistic regression coefficients show each feature's direction and
    # strength (numbers were scaled, so they're comparable). Positive = more
    # likely to renew. These are ASSOCIATIONS, not proof of cause and effect.
    print("\n4. What drives renewal (logistic regression, strongest first)")
    names = logistic.named_steps["prep"].get_feature_names_out()
    coefs = pd.Series(logistic.named_steps["model"].coef_[0], index=names)
    top = coefs.reindex(coefs.abs().sort_values(ascending=False).index).head(8)
    for name, value in top.items():
        direction = "more likely to renew" if value > 0 else "less likely to renew"
        print(f"  {name.split('__')[1]:<28} {value:+.2f}  ({direction})")

    # What-if: how much does the size of the offer matter for current residents?
    print("\n5. What-if: average renewal probability for active leases")
    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    for offer in [0.02, 0.04, 0.06, 0.08]:
        scenario = active.assign(renewal_offer_pct=offer)
        p = chosen.predict_proba(scenario[features])[:, 1].mean()
        print(f"  {offer:.0%} increase offered -> {p:.1%} expected to renew")

    # --- Step 7: score active leases --------------------------------------
    active["renewal_offer_pct"] = ASSUMED_OFFER_PCT
    active["p_renew"] = chosen.predict_proba(active[features])[:, 1].round(3)
    active["risk_tier"] = pd.cut(active["p_renew"], bins=[0, 0.45, 0.6, 1],
                                 labels=["High", "Medium", "Low"], include_lowest=True).astype(str)
    scores = active[["lease_id", "unit_id", "property_id", "lease_end_date",
                     "monthly_rent", "tenure_months", "work_order_count",
                     "p_renew", "risk_tier"]]
    con.register("scores_df", scores)
    con.execute("create or replace table ml.renewal_risk_scores as select * from scores_df")
    con.close()

    MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(chosen, MODEL_PATH)

    print(f"\n6. Scored {len(scores):,} active leases (assuming a {ASSUMED_OFFER_PCT:.0%} offer)")
    print(scores["risk_tier"].value_counts().reindex(["High", "Medium", "Low"]).to_string())
    print(f"\nScores saved to ml.renewal_risk_scores; model saved to {MODEL_PATH.name}")


if __name__ == "__main__":
    main()
