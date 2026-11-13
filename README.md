# Inventory+ Prototype: UC-2 Generate Purchase Request

A small working prototype for **Inventory+**, the agentic AI assisted retail inventory management system
described in our MIS 6308 project report (Systems Analysis and Project Management, Fall 2026, Group 10).
It implements Use Case UC-2, **Generate Purchase Request**, and the Section 16 method contracts and
Structured English algorithms from the report.

The prototype was built with **Claude (Anthropic)** through vibe coding. All data in it is fictional.

## What it does

| Report method | Function in `inventory_core.py` | Behavior |
|---|---|---|
| 16.1 `checkReorderLevel()` | `check_reorder_level` | TRUE when on hand quantity is at or below the reorder point |
| 16.2 `calculateEstimatedValue()` | `calculate_estimated_value` | quantity x unit cost, rejects quantities of zero or less |
| 16.3 `openRequestExists()` | `open_request_exists` | Draft, Pending Approval and Approved count as open |
| 16.4 `generatePurchaseRequest()` | `generate_purchase_request` | validates, blocks duplicates, stores a Draft created by the Agent, writes the audit log |
| 16.5 `processManagerDecision()` | `process_manager_decision` | manager revises quantity, approves, or rejects with a required reason, all audited |

The Streamlit screen (`app.py`) shows the inventory dashboard, the request form, manager review, request
history, the audit log, and a control to clear the demonstration data.

## Run it

Requires Python 3.9 or newer.

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501. A SQLite file (`inventory_plus.db`) is created on first run and
loaded with five fictional items. Use **Prototype Controls** at the bottom of the page to clear requests
and the audit log between demonstrations.

## Test it

```bash
python -m pytest -q
```

22 automated tests cover each method contract: the reorder boundary (on hand equals reorder point),
invalid quantities, duplicate prevention, approval with a revised quantity (5 to 8 gives $199.92),
rejection with and without a reason, and the audit entries.

## Demonstration scenario used for the report figures

1. Open the dashboard: 5 items, 3 need reorder.
2. Select Wireless Mouse, quantity 10: the estimated value is $189.90.
3. Select Laptop Stand, quantity 5, and generate. Generate again: the duplicate is blocked.
4. In Manager Review, change the Laptop Stand quantity from 5 to 8 and approve: value $199.92.
5. Generate and approve a Webcam request (5 units), then generate and reject a Wireless Mouse request.

`docs/capture.py` replays this scenario in a headless browser and saves the screenshots in
`docs/screenshots/` (needs `pip install playwright` and `playwright install chromium`).

## Limits (also stated in report Section 16.7)

* The "Agent" is deterministic Python. No language model is called.
* The reorder quantity formula is not confirmed in the requirements, so quantity is entered by hand.
* The approval threshold amount is not confirmed, so no dollar threshold is applied.
* Vendor selection, purchase orders, delivery tracking and notifications are outside this prototype.

## Files

```
app.py               Streamlit screen
inventory_core.py    business logic and SQLite access
tests/test_core.py   automated tests
docs/capture.py      screenshot script
docs/screenshots/    figures 16.1 to 16.6 used in the report
requirements.txt     dependencies
.streamlit/config.toml  dark theme
```
