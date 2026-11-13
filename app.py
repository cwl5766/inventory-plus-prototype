"""Inventory+ prototype: UC-2 Generate Purchase Request (Streamlit + SQLite).

Run with:  streamlit run app.py
The Agent is deterministic Python logic (see inventory_core.py). No language model is called.
"""
import os

import pandas as pd
import streamlit as st

import inventory_core as core

DB_PATH = os.environ.get("INVENTORY_PLUS_DB", os.path.join(os.path.dirname(__file__), "inventory_plus.db"))

st.set_page_config(page_title="Inventory+", page_icon="📦", layout="wide")


@st.cache_resource
def get_conn():
    conn = core.connect(DB_PATH)
    core.init_db(conn)
    return conn


conn = get_conn()


def flash(kind: str, text: str) -> None:
    st.session_state["flash"] = (kind, text)


def show_flash() -> None:
    kind, text = st.session_state.pop("flash", (None, None))
    if kind:
        getattr(st, kind)(text)


def money(x) -> str:
    return f"${x:,.2f}"


# ------------------------------------------------------------------ header
st.title("📦 Inventory+")
st.subheader("Agentic AI-Assisted Inventory Management System")
st.caption("Prototype for UC-2: Generate Purchase Request")
st.divider()

items = core.list_items(conn)
for i in items:
    i["needs_reorder"] = core.check_reorder_level(i["on_hand_qty"], i["reorder_point"])
n_reorder = sum(i["needs_reorder"] for i in items)
c1, c2, c3 = st.columns(3)
c1.metric("Total Items", len(items))
c2.metric("Reorder Required", n_reorder)
c3.metric("Stock OK", len(items) - n_reorder)
st.divider()

# ------------------------------------------------------------------ dashboard (16.1)
st.header("Inventory Dashboard")
st.caption("Fictional sample data used for prototype demonstration.")
st.dataframe(
    pd.DataFrame([{
        "SKU": i["sku"], "Item": i["name"], "On Hand Qty": i["on_hand_qty"],
        "Reorder Point": i["reorder_point"], "Target Stock Level": i["target_stock_level"],
        "Unit Cost": i["unit_cost"], "Status": "Reorder Required" if i["needs_reorder"] else "Stock OK",
    } for i in items]),
    hide_index=True, use_container_width=True,
    column_config={"Unit Cost": st.column_config.NumberColumn(format="%.2f")},
)
st.divider()

# ------------------------------------------------------------------ generate request (16.2, 16.3, 16.4)
st.header("Generate Purchase Request")
st.write("Select an item that requires replenishment to create a draft purchase request.")
show_flash()
reorder_items = [i for i in items if i["needs_reorder"]]
if not reorder_items:
    st.info("No items are at or below their reorder point.")
else:
    by_name = {i["name"]: i for i in reorder_items}
    name = st.selectbox("Select Item", list(by_name))
    item = by_name[name]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("On Hand Qty", item["on_hand_qty"])
    m2.metric("Reorder Point", item["reorder_point"])
    m3.metric("Target Stock Level", item["target_stock_level"])
    m4.metric("Unit Cost", money(item["unit_cost"]))

    st.subheader("Purchase Request Details")
    st.caption("Prototype assumption: requested quantity is entered manually because the final "
               "reorder-quantity formula has not yet been confirmed.")
    qty = st.number_input("Requested Quantity", min_value=0, value=10, step=1, key=f"qty_{item['item_id']}")
    try:
        st.metric("Estimated Purchase Value", money(core.calculate_estimated_value(int(qty), item["unit_cost"])))
    except core.ValidationError as err:
        st.warning(str(err))
    if st.button("Generate Purchase Request", type="primary"):
        out = core.generate_purchase_request(conn, item["item_id"], int(qty))
        flash({"created": "success", "duplicate": "warning"}.get(out.status, "error"), out.message)
        st.rerun()
st.divider()

# ------------------------------------------------------------------ manager review (16.5)
st.header("Manager Review")
drafts = [r for r in core.list_requests(conn) if r["status"] == "Draft"]
if not drafts:
    st.info("No Draft purchase requests are waiting for review.")
else:
    labels = {f"{r['request_id']}  |  {r['item_name']}  |  Qty {r['requested_qty']}": r for r in drafts}
    choice = st.selectbox("Draft request", list(labels))
    req = labels[choice]
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Item", req["item_name"])
    r2.metric("Requested Quantity", req["requested_qty"])
    r3.metric("Unit Cost", money(req["unit_cost"]))
    r4.metric("Estimated Value", money(req["estimated_value"]))
    new_qty = st.number_input("Revise quantity (optional)", min_value=0, value=int(req["requested_qty"]),
                              step=1, key=f"rev_{req['request_id']}")
    reason = st.text_input("Rejection reason (required to reject)", key=f"why_{req['request_id']}")
    a, b = st.columns(2)
    if a.button("Approve Request", type="primary"):
        out = core.process_manager_decision(conn, req["request_id"], "Approve", revised_qty=int(new_qty))
        flash("success" if out.status == "approved" else "error", out.message)
        st.rerun()
    if b.button("Reject Request"):
        out = core.process_manager_decision(conn, req["request_id"], "Reject", revised_qty=int(new_qty),
                                            rejection_reason=reason)
        flash("success" if out.status == "rejected" else "error", out.message)
        st.rerun()
st.divider()

# ------------------------------------------------------------------ history and audit
st.header("Purchase Request History")
reqs = core.list_requests(conn)
if reqs:
    st.dataframe(pd.DataFrame([{
        "Request ID": r["request_id"], "SKU": r["sku"], "Item": r["item_name"],
        "Requested Quantity": r["requested_qty"], "Unit Cost": money(r["unit_cost"]),
        "Estimated Value": money(r["estimated_value"]), "Status": r["status"],
        "Created By": r["created_by"], "Created At": r["created_at"],
    } for r in reqs]), hide_index=True, use_container_width=True)
else:
    st.info("No purchase requests have been created yet.")
st.divider()

st.header("Audit Log")
log = core.list_audit(conn)
if log:
    st.dataframe(pd.DataFrame([{
        "Log ID": l["log_id"], "Entity Type": l["entity_type"], "Entity ID": l["entity_id"],
        "Action": l["action"], "Actor": l["actor"], "Timestamp": l["timestamp"], "Details": l["details"],
    } for l in log]), hide_index=True, use_container_width=True)
else:
    st.info("The audit log is empty.")
st.divider()

# ------------------------------------------------------------------ prototype controls
st.header("Prototype Controls")
st.caption("Use this option to clear fictional purchase request and audit log data before a new demonstration or test.")
sure = st.checkbox("I understand that this will clear all prototype transaction data.")
if st.button("Clear Prototype Data", disabled=not sure):
    core.reset_transactions(conn)
    flash("success", "Prototype transaction data cleared.")
    st.rerun()
