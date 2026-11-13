"""End-to-end checks of the demo backend in memory mode (no Couchbase, no AOM).

    cd backend && pytest -q
"""
import os
import subprocess
import sys
import time
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = "2026-11-13"
MAYA, DEVON, SOFIA = "S00101001", "S00101002", "S00101003"
MIXER, COFFEE, DOG_FOOD, CONSOLE = "CD-660102", "CD-110245", "CD-550118", "CD-770229"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    dump = tmp_path_factory.mktemp("dump")
    subprocess.run([sys.executable, os.path.join(ROOT, "databricks", "generate_mock_dump.py"),
                    "--export-date", EXPORT, "--target-mb", "3", "--out", str(dump)], check=True,
                   capture_output=True)
    os.environ.update(STORE_DRIVER="memory", DUMP_DIR=str(dump), AOM_URL="", SG_ADMIN_URL="")
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        for _ in range(100):
            if c.get("/api/health").json()["load"] == "loaded":
                break
            time.sleep(0.1)
        yield c


def login(client, member_number, last):
    r = client.post("/api/auth/login", json={"member_number": member_number, "last_name": last})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["customer_id"]


def pull(client, h):
    docs = client.get("/api/sync/pull", headers=h).json()["docs"]
    return {(d["collection"], d["id"]): d["doc"] for d in docs}


def push(client, h, sid, tool, args):
    oid = f"order::{sid}::{uuid.uuid4().hex[:12]}"
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "orders", "id": oid, "doc": {
        "type": "request", "customer_id": sid, "tool": tool, "args": args, "created_at": f"{EXPORT}T01:00:00Z"}}]})
    assert r.status_code == 200, r.text
    for _ in range(50):
        d = pull(client, h).get(("orders", oid))
        if d and d["status"] not in ("pending", "processing"):
            return d
        time.sleep(0.1)
    raise AssertionError("order never processed")


def smart_cart(recs):
    return [{"sku": l["sku"], "qty": l["qty"]} for l in recs["lines"] if l["selected"]]


def test_personas_and_login(client):
    ps = client.get("/api/demo/personas").json()["personas"]
    assert [p["customer_id"] for p in ps] == [MAYA, DEVON, SOFIA]
    assert ps[0]["tier"] == "Plus" and ps[0]["smart_cart_items"] == 8 and ps[0]["home_hub"] == "Salem Hub"
    assert client.post("/api/auth/login", json={"member_number": "204817", "last_name": "Nope"}).status_code == 401


def test_profile_recommendations_and_store_sync(client):
    h, sid = login(client, "204817", "Chen")
    docs = pull(client, h)
    me = docs[("customers", f"customer::{sid}")]
    assert me["engagement"]["connectivity_note"].startswith("Subway")
    recs = docs[("recommendations", f"recs::{sid}")]
    assert {l["sku"] for l in recs["lines"][:2]} == {"CD-440129", COFFEE}
    assert all(l["unit_price"] < l["list_price"] for l in recs["lines"])  # Plus pricing
    assert recs["for_you"][0]["sku"] == MIXER
    pm = recs["price_matches"][0]
    assert pm["sku"] == MIXER and pm["competitor"] == "Brightway Market" and pm["saving_usd"] == 26.0  # the price-match story
    assert ("catalog", "catalog::v1") in docs
    store = docs[("hubs", "hub::HB-0101")]
    assert store["name"] == "Salem Hub" and store["bays"][MIXER].startswith("F")
    # only this customer's profile and home store sync, nobody else's
    assert [k for k in docs if k[0] == "customers"] == [("customers", f"customer::{sid}")]
    assert [k for k in docs if k[0] == "hubs"] == [("hubs", "hub::HB-0101")]


def test_price_match_order_and_partial_shipment(client):
    h, sid = login(client, "204817", "Chen")
    recs = pull(client, h)[("recommendations", f"recs::{sid}")]
    lines = smart_cart(recs) + [{"sku": MIXER, "qty": 1}]
    r = push(client, h, sid, "request_price_match", {"lines": lines, "sku": MIXER, "competitor": "Brightway Market",
                                                    "competitor_price_usd": 239.99})
    # FC-NE holds one box of coffee pods; the cart asks for two.
    assert r["status"] == "partially_shipped", r
    assert r["item"]["backordered"][0]["sku"] == COFFEE
    assert r["item"]["price_match"]["saved_usd"] == 26.0
    mixer = next(l for l in r["item"]["lines"] if l["sku"] == MIXER)
    assert mixer["unit_price"] == 239.99 and mixer["price_matched"]
    assert r["item"]["store_credit_applied_usd"] == 12.5 and r["charge_usd"] == r["item"]["amount_due_usd"]
    docs = pull(client, h)
    me = docs[("customers", f"customer::{sid}")]
    assert me["order_history"][0]["order_id"] == r["item"]["order_id"]
    assert me["wallet"]["store_credit_usd"] == 0 and me["wallet"]["points"] > 1840
    # the recommendations re-ranked: what was just ordered is gone, and so is the price match
    recs2 = docs[("recommendations", f"recs::{sid}")]
    assert not recs2["lines"] and not recs2["price_matches"]
    assert not any(f["sku"] == MIXER for f in recs2["for_you"])


def test_price_match_guardrails(client):
    h, sid = login(client, "318552", "Walker")
    lines = [{"sku": "CD-550590", "qty": 1}]
    r = push(client, h, sid, "request_price_match", {"lines": lines, "sku": "CD-550590", "competitor": "Some Other Shop",
                                                    "competitor_price_usd": 49.99})
    assert r["status"] == "failed" and "Brightway" in r["summary"]
    r = push(client, h, sid, "request_price_match", {"lines": lines, "sku": "CD-550590", "competitor": "Oakline Stores",
                                                    "competitor_price_usd": 9.99})
    assert r["status"] == "failed" and "below" in r["summary"]


def test_assistant_context_cache_and_guide(client):
    h, sid = login(client, "318552", "Walker")
    a = client.post("/api/assistant", headers=h, json={"message": "What am I running low on?"}).json()
    assert a["intent"] == "reorder" and a["personal"] and a["context"]["status"] == "miss"
    assert any(x.get("tool") == "place_order" for x in a["actions"])
    assert "dog food" in a["reply"].lower()
    b = client.post("/api/assistant", headers=h, json={"message": "Anything I should restock?"}).json()
    assert b["context"]["status"] == "hit"
    g = client.post("/api/assistant", headers=h, json={"message": "How does a price match work?"}).json()
    assert g["personal"] is False and "customer care" in g["reply"].lower()
    p = client.post("/api/assistant", headers=h, json={"message": "How much is the pet bed?"}).json()
    assert p["personal"] and "$59.99" in p["reply"]  # Member tier pays list
    q = client.post("/api/assistant", headers=h, json={"message": "How much is the yoga mat?"}).json()
    assert q["context"]["status"] == "hit" and "yoga mat" in q["reply"].lower()  # cached context, live item lookup
    docs = pull(client, h)
    assert ("context_cache", f"ctx::{sid}::reorder") in docs and ("context_cache", f"ctx::{sid}::guide_pricing") in docs


def test_backorder_and_subscription(client):
    h, sid = login(client, "318552", "Walker")
    # FC-NY is out of the dog food: the whole line backorders, the order still goes through.
    r = push(client, h, sid, "place_order", {"lines": [{"sku": DOG_FOOD, "qty": 2}, {"sku": "CD-550472", "qty": 1}]})
    assert r["status"] == "partially_shipped" and r["item"]["backordered"][0] == {**r["item"]["backordered"][0], "sku": DOG_FOOD, "qty": 2}
    assert r["item"]["delivery_fee_usd"] == 0  # Member tier, over $35
    r = push(client, h, sid, "set_subscription", {"sku": DOG_FOOD, "qty": 2, "cadence_weeks": 4})
    assert r["status"] == "confirmed" and r["item"]["cadence_weeks"] == 4
    r = push(client, h, sid, "set_subscription", {"sku": "CD-550590", "qty": 1})
    assert r["status"] == "failed" and "Subscribe & Save" in r["summary"]
    recs = pull(client, h)[("recommendations", f"recs::{sid}")]
    assert not any(l["sku"] == DOG_FOOD for l in recs["lines"])


def test_purchase_limit_and_business_rules(client):
    h, sid = login(client, "427190", "Alvarez")
    r = push(client, h, sid, "place_order", {"lines": [{"sku": CONSOLE, "qty": 1}, {"sku": "CD-110777", "qty": 3}]})
    assert r["status"] == "failed" and r["reason_code"] == "purchase_limit", r
    assert r["purchase_limits"][0]["already_bought"] == 1
    a = client.post("/api/assistant", headers=h, json={"message": "Why can't I buy a second console?"}).json()
    assert a["personal"] and "limited to 1 per household" in a["reply"]
    r = push(client, h, sid, "place_order", {"lines": [{"sku": "CD-110777", "qty": 3}], "delivery_option": "Hub pickup"})
    assert r["status"] == "confirmed" and r["item"]["pickup_hub"] == "Plano Hub"
    assert r["item"]["lines"][0]["unit_price"] == round(11.99 * 0.85, 2)  # Premier 10% + multi-buy 5%
    r = push(client, h, sid, "place_order", {"lines": [{"sku": "CD-000000", "qty": 1}]})
    assert r["status"] == "failed" and "Unknown item" in r["summary"]
    r = push(client, h, sid, "get_recommendations", {})
    assert r["status"] == "failed"  # read-only tools can't be requested from the phone


def test_preferences_rerank_recommendations(client):
    h, sid = login(client, "427190", "Alvarez")
    before = pull(client, h)[("recommendations", f"recs::{sid}")]
    assert any(f["category"] == "electronics" for f in before["for_you"])
    r = push(client, h, sid, "update_preferences", {"favorite_categories": ["kitchen"], "avoid_categories": ["electronics"],
                                                   "default_delivery_option": "Hub pickup"})
    assert r["status"] == "confirmed"
    docs = pull(client, h)
    after = docs[("recommendations", f"recs::{sid}")]
    assert not any(f["category"] == "electronics" for f in after["for_you"])
    assert after["for_you"][0]["category"] == "kitchen"
    assert docs[("customers", f"customer::{sid}")]["delivery"]["default_option"] == "Hub pickup"
    r = push(client, h, sid, "update_preferences", {"favorite_categories": ["toys"], "avoid_categories": ["toys"]})
    assert r["status"] == "failed"


def test_return_and_goodwill_go_to_store_credit(client):
    h, sid = login(client, "427190", "Alvarez")
    me = pull(client, h)[("customers", f"customer::{sid}")]
    order = next(o for o in me["order_history"] if any(l["sku"] == "CD-880243" for l in o["lines"]))
    before = me["wallet"]["store_credit_usd"]
    r = push(client, h, sid, "create_return", {"order_id": order["order_id"], "sku": "CD-880243", "qty": 1, "reason": "Duplicate gift"})
    assert r["status"] == "confirmed" and r["charge_usd"] < 0 and r["item"]["drop_off"] == "Plano Hub"
    r2 = push(client, h, sid, "create_return", {"order_id": order["order_id"], "sku": "CD-880243", "qty": 1, "reason": "Again"})
    assert r2["status"] == "failed"  # already returned
    g = push(client, h, sid, "issue_goodwill_credit", {"amount_usd": 15, "reason": "Delivery arrived with a crushed box"})
    assert g["status"] == "confirmed"
    after = pull(client, h)[("customers", f"customer::{sid}")]["wallet"]["store_credit_usd"]
    assert after == round(before + r["item"]["refund_usd"] + 15, 2)
    g = push(client, h, sid, "issue_goodwill_credit", {"amount_usd": 500, "reason": "Too much"})
    assert g["status"] == "failed"


def test_push_rejects_other_customers(client):
    h, sid = login(client, "427190", "Alvarez")
    r = client.post("/api/sync/push", headers=h, json={"docs": [{"collection": "orders", "id": f"order::{MAYA}::x",
                                                                 "doc": {"customer_id": MAYA, "tool": "place_order"}}]})
    assert r.status_code == 403


def test_databricks_offload_metrics(client):
    m = client.get("/api/status").json()["metrics"]
    assert m["warehouse_queries_avoided"] > 0 and m["estimated_dbx_spend_avoided_usd"] > 0
    assert m["orders_confirmed"] >= 3 and m["orders_queued_offline"] >= 1


def test_delivery_plan_window_and_drop_off(client):
    h, sid = login(client, "318552", "Walker")
    docs = pull(client, h)
    me = docs[("customers", f"customer::{sid}")]
    assert me["delivery"]["preferred_window"] == "12-2 pm" and me["delivery"]["notes"] == "Back porch, not the front steps"
    hub = docs[("hubs", "hub::HB-0202")]
    assert 25 <= hub["express_eta_minutes"] < 55 and hub["name"] == "Rhinebeck Hub"
    # the customer changes how they want deliveries left; the next order carries it to the courier
    r = push(client, h, sid, "update_preferences", {"delivery_notes": "Gate code 4411, leave in the mudroom",
                                                   "preferred_window": "5-7 pm"})
    assert r["status"] == "confirmed" and "Gate code 4411" in r["summary"]
    r = push(client, h, sid, "update_preferences", {"preferred_window": "midnight"})
    assert r["status"] == "failed" and "Delivery window" in r["summary"]
    r = push(client, h, sid, "place_order", {"lines": [{"sku": "CD-110777", "qty": 1}], "delivery_option": "Express delivery"})
    plan = r["item"]["delivery"]
    assert r["status"] == "confirmed" and plan["hub"] == "Rhinebeck Hub" and plan["stage"] == "packing"
    assert plan["eta_minutes"] == hub["express_eta_minutes"] and plan["courier"]["name"]
    assert plan["drop_off"] == "Gate code 4411, leave in the mudroom" and "Drop-off: Gate code 4411" in r["summary"]
    r = push(client, h, sid, "place_order", {"lines": [{"sku": "CD-110777", "qty": 1}], "delivery_option": "Scheduled delivery"})
    assert r["item"]["delivery"]["window"] == "Tomorrow, 5-7 pm" and r["item"]["eta"] > r["item"]["date"]
    r = push(client, h, sid, "place_order", {"lines": [{"sku": "CD-110777", "qty": 1}], "delivery_option": "Hub pickup"})
    assert r["item"]["delivery"]["courier"] is None and r["item"]["delivery"]["drop_off"] is None
    r = push(client, h, sid, "place_order", {"lines": [{"sku": "CD-110777", "qty": 1}], "delivery_option": "2-day shipping"})
    assert r["status"] == "failed"
    a = client.post("/api/assistant", headers=h, json={"message": "What are my drop-off instructions for the courier?"}).json()
    assert a["personal"] and "Gate code 4411" in a["reply"] and "5-7 pm" in a["reply"], a["reply"]
