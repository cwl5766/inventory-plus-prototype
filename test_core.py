import sqlite3
import pytest
from datetime import datetime, timedelta
import inventory_core as core


@pytest.fixture()
def conn():
    c = core.connect(":memory:")
    core.init_db(c)
    return c


def item_id(conn, sku):
    return conn.execute("SELECT item_id FROM item WHERE sku=?", (sku,)).fetchone()[0]


# 16.1
def test_reorder_boundary_equal_is_true():
    assert core.check_reorder_level(10, 10) is True


def test_reorder_below_and_above():
    assert core.check_reorder_level(8, 10) is True
    assert core.check_reorder_level(35, 20) is False


def test_reorder_rejects_negative():
    with pytest.raises(core.ValidationError):
        core.check_reorder_level(-1, 10)


# 16.2
def test_value_matches_report_examples():
    assert core.calculate_estimated_value(10, 18.99) == 189.90
    assert core.calculate_estimated_value(8, 24.99) == 199.92
    assert core.calculate_estimated_value(5, 39.99) == 199.95


@pytest.mark.parametrize("qty", [0, -3])
def test_value_requires_positive_qty(qty):
    with pytest.raises(core.ValidationError):
        core.calculate_estimated_value(qty, 5.0)


# 16.3 and 16.4
def test_seed_data_has_three_items_to_reorder(conn):
    items = core.list_items(conn)
    assert len(items) == 5
    assert sum(core.check_reorder_level(i["on_hand_qty"], i["reorder_point"]) for i in items) == 3


def test_generate_creates_draft_and_audit(conn):
    out = core.generate_purchase_request(conn, item_id(conn, "SKU-003"), 5)
    assert out.status == "created"
    req = core.list_requests(conn)[0]
    assert (req["status"], req["created_by"], req["estimated_value"]) == ("Draft", "Agent", 124.95)
    log = core.list_audit(conn)
    assert len(log) == 1 and log[0]["action"] == "Draft Created" and log[0]["actor"] == "Agent"


def test_generate_blocks_item_not_at_reorder_point(conn):
    out = core.generate_purchase_request(conn, item_id(conn, "SKU-002"), 5)
    assert out.status == "no_replenishment"
    assert core.list_requests(conn) == []


@pytest.mark.parametrize("qty", [0, -1])
def test_generate_rejects_invalid_quantity(conn, qty):
    out = core.generate_purchase_request(conn, item_id(conn, "SKU-001"), qty)
    assert out.status == "validation_error" and core.list_requests(conn) == []


def test_duplicate_open_request_is_blocked(conn):
    iid = item_id(conn, "SKU-001")
    assert core.generate_purchase_request(conn, iid, 10).status == "created"
    assert core.open_request_exists(conn, iid)
    again = core.generate_purchase_request(conn, iid, 10)
    assert again.status == "duplicate"
    assert len(core.list_requests(conn)) == 1 and len(core.list_audit(conn)) == 1


def test_approved_request_still_counts_as_open(conn):
    iid = item_id(conn, "SKU-001")
    rid = core.generate_purchase_request(conn, iid, 10).request_id
    core.process_manager_decision(conn, rid, "Approve")
    assert core.open_request_exists(conn, iid)


def test_rejected_request_frees_the_item(conn):
    iid = item_id(conn, "SKU-001")
    rid = core.generate_purchase_request(conn, iid, 10).request_id
    core.process_manager_decision(conn, rid, "Reject", rejection_reason="Quantity requires further review")
    assert not core.open_request_exists(conn, iid)
    assert core.generate_purchase_request(conn, iid, 10).status == "created"


# 16.5
def test_approve_with_quantity_change_recalculates(conn):
    rid = core.generate_purchase_request(conn, item_id(conn, "SKU-003"), 5).request_id
    out = core.process_manager_decision(conn, rid, "Approve", revised_qty=8)
    assert out.status == "approved"
    req = core.list_requests(conn)[0]
    assert (req["status"], req["requested_qty"], req["estimated_value"]) == ("Approved", 8, 199.92)
    last = core.list_audit(conn)[0]
    assert last["action"] == "Approved" and "from 5 to 8" in last["details"] and "$199.92" in last["details"]


def test_approve_without_change(conn):
    rid = core.generate_purchase_request(conn, item_id(conn, "SKU-005"), 5).request_id
    core.process_manager_decision(conn, rid, "Approve")
    assert "without changing quantity" in core.list_audit(conn)[0]["details"]


def test_reject_requires_reason(conn):
    rid = core.generate_purchase_request(conn, item_id(conn, "SKU-001"), 10).request_id
    out = core.process_manager_decision(conn, rid, "Reject", rejection_reason="  ")
    assert out.status == "validation_error"
    assert core.list_requests(conn)[0]["status"] == "Draft"


def test_reject_records_reason(conn):
    rid = core.generate_purchase_request(conn, item_id(conn, "SKU-001"), 10).request_id
    assert core.process_manager_decision(conn, rid, "Reject", rejection_reason="Too many").status == "rejected"
    last = core.list_audit(conn)[0]
    assert last["action"] == "Rejected" and "Reason: Too many" in last["details"]


def test_revised_quantity_must_be_positive(conn):
    rid = core.generate_purchase_request(conn, item_id(conn, "SKU-001"), 10).request_id
    out = core.process_manager_decision(conn, rid, "Approve", revised_qty=0)
    assert out.status == "validation_error" and core.list_requests(conn)[0]["status"] == "Draft"


def test_invalid_decision_and_double_review(conn):
    rid = core.generate_purchase_request(conn, item_id(conn, "SKU-001"), 10).request_id
    assert core.process_manager_decision(conn, rid, "Maybe").status == "invalid_decision"
    core.process_manager_decision(conn, rid, "Approve")
    assert core.process_manager_decision(conn, rid, "Approve").status == "not_reviewable"


def test_reset_clears_transactions_only(conn):
    core.generate_purchase_request(conn, item_id(conn, "SKU-001"), 10)
    core.reset_transactions(conn)
    assert core.list_requests(conn) == [] and core.list_audit(conn) == [] and len(core.list_items(conn)) == 5


def test_reset_restarts_audit_numbering(conn):
    core.generate_purchase_request(conn, item_id(conn, "SKU-001"), 10)
    core.reset_transactions(conn)
    core.generate_purchase_request(conn, item_id(conn, "SKU-001"), 10)
    assert core.list_audit(conn)[0]["log_id"] == 1
