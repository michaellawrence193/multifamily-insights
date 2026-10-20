"""
"Known answer" tests: the generator recorded exactly which records it
corrupted (data/raw/_planted_issues.json). Each test checks that the
pipeline handled that issue correctly -- caught every planted record, and
didn't flag any good ones.

Comparing sets of IDs (not just counts) matters: a check that catches 4
records could still be catching the WRONG 4.
"""

from conftest import ids


def test_duplicates_exist_in_raw_but_not_in_staging(con, answer_key):
    raw_dupes = ids(con, """
        select lease_id from raw.leases group by lease_id having count(*) > 1
    """)
    assert raw_dupes == set(answer_key["duplicate_leases"])

    staged_dupes = ids(con, """
        select lease_id from staging.stg_leases group by lease_id having count(*) > 1
    """)
    assert staged_dupes == set()


def test_orphan_leases_are_rejected(con, answer_key):
    rejected = ids(con, """
        select record_id from audit.rejected_records
        where dq_issue = 'unit_id not found in units'
    """)
    assert rejected == set(answer_key["orphan_unit_leases"])


def test_backwards_date_leases_are_rejected(con, answer_key):
    rejected = ids(con, """
        select record_id from audit.rejected_records
        where dq_issue = 'lease ends before it starts'
    """)
    assert rejected == set(answer_key["end_before_start_leases"])


def test_invalid_rent_leases_are_rejected(con, answer_key):
    rejected = ids(con, """
        select record_id from audit.rejected_records
        where dq_issue = 'monthly_rent is zero or negative'
    """)
    assert rejected == set(answer_key["invalid_rent_leases"])


def test_backwards_work_orders_are_rejected(con, answer_key):
    rejected = ids(con, """
        select record_id from audit.rejected_records
        where dq_issue = 'completed before opened'
    """)
    assert rejected == set(answer_key["completed_before_opened_work_orders"])


def test_nothing_rejected_that_was_not_planted(con, answer_key):
    planted = set().union(
        answer_key["orphan_unit_leases"],
        answer_key["end_before_start_leases"],
        answer_key["invalid_rent_leases"],
        answer_key["completed_before_opened_work_orders"],
    )
    rejected = ids(con, "select record_id from audit.rejected_records")
    assert rejected == planted, f"Unexpected rejections: {rejected - planted}"


def test_state_codes_are_standardized(con, answer_key):
    fixed = dict(con.execute(f"""
        select property_id, state_code from marts.dim_properties
        where property_id in {tuple(answer_key["nonstandard_state_properties"])}
    """).fetchall())
    assert fixed == {"P003": "GA", "P006": "TX"}


def test_missing_emails_are_kept_and_surfaced(con, answer_key):
    # Incomplete, not wrong: these residents must still exist in the mart,
    # with the gap made visible rather than hidden.
    flagged = ids(con, """
        select resident_id from marts.dim_residents where not has_email_on_file
    """)
    assert flagged == set(answer_key["missing_email_residents"])
