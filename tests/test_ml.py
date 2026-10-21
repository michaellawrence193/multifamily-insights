"""
Tests for the machine-learning layer: the features must respect the grain,
must not leak the outcome, and the risk scores must be sane.
"""

import pytest


def test_features_one_row_per_lease(con):
    rows, leases = con.execute("""
        select count(*), count(distinct lease_id) from ml.lease_renewal_features
    """).fetchone()
    assert rows == leases


def test_features_cover_every_valid_lease(con):
    in_mart = con.execute("select count(*) from marts.fct_leases").fetchone()[0]
    in_features = con.execute("select count(*) from ml.lease_renewal_features").fetchone()[0]
    assert in_features == in_mart, "Features table dropped or duplicated leases in a join"


def test_label_is_null_only_for_active_leases(con):
    mismatches = con.execute("""
        select f.lease_id
        from ml.lease_renewal_features f
        join marts.fct_leases l using (lease_id)
        where (f.renewed is null) != (l.lease_status = 'Active')
    """).fetchall()
    assert mismatches == []


def test_no_outcome_columns_in_features(con):
    # Columns that reveal what happened AFTER the renewal decision must never
    # be model inputs. This guards against someone adding one later.
    leaky = con.execute("""
        select column_name from information_schema.columns
        where table_schema = 'ml' and table_name = 'lease_renewal_features'
          and (column_name in ('lease_status', 'move_out_date') or column_name like 'next_%')
    """).fetchall()
    assert leaky == [], f"Possible leakage columns: {leaky}"


def scores_exist(con):
    return con.execute("""
        select count(*) from information_schema.tables
        where table_schema = 'ml' and table_name = 'renewal_risk_scores'
    """).fetchone()[0] == 1


def test_every_active_lease_is_scored_once(con):
    if not scores_exist(con):
        pytest.skip("Run src/train_model.py to create risk scores")
    active, scored, distinct = con.execute("""
        select
            (select count(*) from marts.fct_leases where lease_status = 'Active'),
            (select count(*) from ml.renewal_risk_scores),
            (select count(distinct lease_id) from ml.renewal_risk_scores)
    """).fetchone()
    assert active == scored == distinct


def test_scores_are_valid_probabilities(con):
    if not scores_exist(con):
        pytest.skip("Run src/train_model.py to create risk scores")
    bad = con.execute("""
        select count(*) from ml.renewal_risk_scores
        where p_renew not between 0 and 1 or risk_tier not in ('High', 'Medium', 'Low')
    """).fetchone()[0]
    assert bad == 0
