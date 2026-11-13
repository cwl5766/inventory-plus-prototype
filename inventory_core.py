"""Business logic for the Inventory+ prototype (UC-2: Generate Purchase Request).

Each public function follows a method contract from Section 16 of the project report:
    check_reorder_level            -> 16.1 checkReorderLevel()
    calculate_estimated_value      -> 16.2 calculateEstimatedValue()
    open_request_exists            -> 16.3 openRequestExists()
    generate_purchase_request      -> 16.4 generatePurchaseRequest()
    process_manager_decision       -> 16.5 processManagerDecision()
    write_audit_log                -> helper used by 16.4 and 16.5

The "Agent" in this prototype is deterministic Python logic. It does not call a language model.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# Prototype assumption (report Section 16.3): these statuses count as an open request.
OPEN_STATUSES = ("Draft", "Pending Approval", "Approved")

SEED_ITEMS = [
    # sku, name, on_hand_qty, reorder_point, target_stock_level, unit_cost
    ("SKU-001", "Wireless Mouse", 8, 10, 30, 18.99),
    ("SKU-002", "USB-C Cable", 35, 20, 50, 7.50),
    ("SKU-003", "Laptop Stand", 10, 10, 25, 24.99),
    ("SKU-004", "Keyboard", 22, 15, 40, 29.99),
    ("SKU-005", "Webcam", 4, 8, 20, 39.99),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS item (
    item_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sku                TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    on_hand_qty        INTEGER NOT NULL CHECK (on_hand_qty >= 0),
    reorder_point      INTEGER NOT NULL CHECK (reorder_point >= 0),
    target_stock_level INTEGER NOT NULL CHECK (target_stock_level >= 0),
    unit_cost          REAL NOT NULL CHECK (unit_cost >= 0)
);
CREATE TABLE IF NOT EXISTS purchase_request (
    request_id       TEXT PRIMARY KEY,
    item_id          INTEGER NOT NULL REFERENCES item(item_id),
    requested_qty    INTEGER NOT NULL CHECK (requested_qty > 0),
    unit_cost        REAL NOT NULL,
    estimated_value  REAL NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('Draft','Pending Approval','Approved','Rejected')),
    created_by       TEXT NOT NULL CHECK (created_by IN ('Agent','Manager')),
    created_at       TEXT NOT NULL,
    decided_at       TEXT,
    rejection_reason TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    details     TEXT NOT NULL
);
"""


class ValidationError(ValueError):
    """Raised when an input breaks a method pre-condition."""


@dataclass
class Outcome:
    """Result of generate_purchase_request or process_manager_decision."""
    status: str          # created | no_replenishment | validation_error | duplicate | approved | rejected | invalid_decision | not_reviewable
    message: str
    request_id: Optional[str] = None


# --------------------------------------------------------------------------- setup
def connect(path: str = "inventory_plus.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and load the fictional sample items if the item table is empty."""
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO item (sku, name, on_hand_qty, reorder_point, target_stock_level, unit_cost) "
            "VALUES (?,?,?,?,?,?)",
            SEED_ITEMS,
        )
    conn.commit()


def reset_transactions(conn: sqlite3.Connection) -> None:
    """Prototype control: clear fictional requests and audit entries before a new demonstration."""
    conn.execute("DELETE FROM purchase_request")
    conn.execute("DELETE FROM audit_log")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'audit_log'")  # restart log numbering at 1
    conn.commit()


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- 16.1
def check_reorder_level(on_hand_qty: int, reorder_point: int) -> bool:
    """TRUE when on_hand_qty is at or below reorder_point. Inventory is not changed."""
    if on_hand_qty < 0 or reorder_point < 0:
        raise ValidationError("Quantities must be non-negative.")
    return on_hand_qty <= reorder_point


# --------------------------------------------------------------------------- 16.2
def calculate_estimated_value(requested_qty: int, unit_cost: float) -> float:
    """estimated_value = requested_qty x unit_cost, rounded to cents."""
    if requested_qty is None or requested_qty <= 0:
        raise ValidationError("Requested quantity must be greater than zero.")
    if unit_cost < 0:
        raise ValidationError("Unit cost must not be negative.")
    value = (Decimal(str(unit_cost)) * Decimal(requested_qty)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return float(value)


# --------------------------------------------------------------------------- 16.3
def open_request_exists(conn: sqlite3.Connection, item_id: int) -> bool:
    """TRUE when the item already has a Draft, Pending Approval or Approved request."""
    marks = ",".join("?" for _ in OPEN_STATUSES)
    row = conn.execute(
        f"SELECT 1 FROM purchase_request WHERE item_id = ? AND status IN ({marks}) LIMIT 1",
        (item_id, *OPEN_STATUSES),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- audit helper
def write_audit_log(conn, entity_id: str, action: str, actor: str, details: str, when: datetime) -> None:
    conn.execute(
        "INSERT INTO audit_log (entity_type, entity_id, action, actor, timestamp, details) VALUES (?,?,?,?,?,?)",
        ("PurchaseRequest", entity_id, action, actor, _stamp(when), details),
    )


# --------------------------------------------------------------------------- 16.4
def generate_purchase_request(conn, item_id: int, requested_qty: int, now: Optional[datetime] = None) -> Outcome:
    """Validate, block duplicates, price the request, store a Draft created by the Agent, and audit it."""
    now = now or datetime.now()
    item = conn.execute("SELECT * FROM item WHERE item_id = ?", (item_id,)).fetchone()
    if item is None:
        return Outcome("validation_error", "Item not found.")
    if not check_reorder_level(item["on_hand_qty"], item["reorder_point"]):
        return Outcome("no_replenishment", f"{item['name']} does not require replenishment.")
    try:
        value = calculate_estimated_value(requested_qty, item["unit_cost"])
    except ValidationError as err:
        return Outcome("validation_error", str(err))
    if open_request_exists(conn, item_id):
        return Outcome("duplicate", f"An open purchase request already exists for {item['name']}. No duplicate was created.")
    request_id = "PR-" + now.strftime("%Y%m%d%H%M%S%f")
    with conn:
        conn.execute(
            "INSERT INTO purchase_request (request_id, item_id, requested_qty, unit_cost, estimated_value, "
            "status, created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (request_id, item_id, requested_qty, item["unit_cost"], value, "Draft", "Agent", _stamp(now)),
        )
        write_audit_log(conn, request_id, "Draft Created", "Agent",
                        f"Draft purchase request created for {item['name']} with requested quantity {requested_qty}.", now)
    return Outcome("created", f"Draft purchase request created for {item['name']}.", request_id)


# --------------------------------------------------------------------------- 16.5
def process_manager_decision(conn, request_id: str, decision: str, revised_qty: Optional[int] = None,
                             rejection_reason: Optional[str] = None, now: Optional[datetime] = None) -> Outcome:
    """Manager reviews a Draft: optionally revise the quantity, then approve or reject with an audit entry."""
    now = now or datetime.now()
    req = conn.execute(
        "SELECT r.*, i.name AS item_name FROM purchase_request r JOIN item i USING(item_id) WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if req is None or req["status"] != "Draft":
        return Outcome("not_reviewable", "The request does not exist or is no longer awaiting review.", request_id)
    if decision not in ("Approve", "Reject"):
        return Outcome("invalid_decision", "Decision must be Approve or Reject.", request_id)

    qty, value, changed = req["requested_qty"], req["estimated_value"], False
    if revised_qty is not None and revised_qty != req["requested_qty"]:
        try:
            value = calculate_estimated_value(revised_qty, req["unit_cost"])
        except ValidationError as err:
            return Outcome("validation_error", str(err), request_id)
        qty, changed = revised_qty, True

    if decision == "Reject" and not (rejection_reason or "").strip():
        return Outcome("validation_error", "A rejection reason is required.", request_id)

    with conn:
        if decision == "Approve":
            conn.execute(
                "UPDATE purchase_request SET requested_qty=?, estimated_value=?, status='Approved', decided_at=? "
                "WHERE request_id=?", (qty, value, _stamp(now), request_id))
            if changed:
                details = (f"Manager approved request. Quantity changed from {req['requested_qty']} to {qty}. "
                           f"Revised value: ${value:,.2f}.")
            else:
                details = f"Manager approved request without changing quantity. Value: ${value:,.2f}."
            write_audit_log(conn, request_id, "Approved", "Manager", details, now)
            return Outcome("approved", f"Request approved. Estimated value ${value:,.2f}.", request_id)
        reason = rejection_reason.strip()
        conn.execute(
            "UPDATE purchase_request SET requested_qty=?, estimated_value=?, status='Rejected', decided_at=?, "
            "rejection_reason=? WHERE request_id=?", (qty, value, _stamp(now), reason, request_id))
        write_audit_log(conn, request_id, "Rejected", "Manager", f"Manager rejected request. Reason: {reason}", now)
        return Outcome("rejected", "Request rejected and the reason was recorded.", request_id)


# --------------------------------------------------------------------------- queries for the UI
def list_items(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM item ORDER BY sku")]


def list_requests(conn):
    return [dict(r) for r in conn.execute(
        "SELECT r.*, i.sku, i.name AS item_name FROM purchase_request r JOIN item i USING(item_id) "
        "ORDER BY r.created_at DESC, r.request_id DESC")]


def list_audit(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY log_id DESC")]
