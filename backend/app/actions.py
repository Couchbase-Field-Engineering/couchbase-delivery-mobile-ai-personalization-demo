"""Delivery actions - the business logic behind every MCP tool.

These functions are what actually changes state (orders, inventory, store
credit, subscriptions, returns, preferences). They are only ever reached
through `tool_gateway`, which routes them through the Couchbase Agent
Operations Manager when it is configured (RBAC, approvals, tracing, audit) and
calls them in-process otherwise. Every mutation bumps the customer's `rev`,
which is what invalidates that customer's context cache and re-ranks their
recommendations.

Every tool takes the `customer_id` it acts for. The worker fills it from the
order document, which Sync Gateway only accepted from that signed-in customer,
and the assistant fills it from the app token; a customer can only ever act on
their own profile.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid

from . import catalog as C
from .docs import days_since, inventory_id, money, now_iso, customer_id_doc, today
from .store import store


class ToolError(Exception):
    pass


def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def short(name: str) -> str:
    """Product name without the pack-size tail, for sentences."""
    return name.split(",")[0]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def load_customer(customer_id: str) -> dict:
    s = await store.get("customers", customer_id_doc(customer_id))
    if not s:
        raise ToolError(f"No customer '{customer_id}'")
    return s


async def save_customer(s: dict):
    s["rev"] = int(s.get("rev", 0)) + 1
    s["updated_at"] = now_iso()
    await store.upsert("customers", customer_id_doc(s["customer_id"]), s)
    from .loader import mark_live  # late import: loader -> personalization -> actions
    await mark_live(s["customer_id"])


async def after_change(customer_id: str):
    # late imports: personalization/assistant import this module
    from . import assistant, personalization
    await personalization.refresh_recommendations(customer_id)
    await assistant.invalidate_context(customer_id)


async def get_inventory(fc: str) -> tuple[dict, int]:
    doc, cas = await store.get_with_cas("inventory", inventory_id(fc))
    if doc is None:
        await store.insert("inventory", inventory_id(fc),
                           {"type": "inventory", "fc": fc, "fc_name": C.FULFILLMENT_CENTERS[fc]["name"],
                            "on_hand": C.initial_inventory(fc), "created_at": now_iso()})
        doc, cas = await store.get_with_cas("inventory", inventory_id(fc))
    return doc, cas


async def allocate_inventory(fc: str, wants: dict[str, int]) -> dict[str, int]:
    """Take what is on hand for each SKU (CAS-protected). Returns what was
    actually allocated per SKU; the rest is backordered."""
    for _ in range(10):
        doc, cas = await get_inventory(fc)
        got = {}
        for sku, qty in wants.items():
            avail = max(0, int(doc["on_hand"].get(sku, 0)))
            got[sku] = min(avail, int(qty))
            doc["on_hand"][sku] = avail - got[sku]
        doc["updated_at"] = now_iso()
        if await store.replace_cas("inventory", inventory_id(fc), doc, cas):
            return got
    raise ToolError("Inventory is busy - please try again")


def _line(s: dict, sku: str, qty: int, matched_unit: float | None = None) -> dict:
    p = C.PRODUCT_BY_SKU.get(sku)
    if not p:
        raise ToolError(f"Unknown item '{sku}'")
    qty = int(qty)
    if qty < 1 or qty > 24:
        raise ToolError(f"Quantity for {short(p['name'])} must be between 1 and 24")
    unit = C.member_price(sku, s["membership"]["tier"], qty)
    line = {"sku": sku, "name": p["name"], "category": p["category"], "uom": p["uom"], "qty": qty,
            "list_price": p["list_price"], "unit_price": unit, "line_total": round(unit * qty, 2),
            "savings": round((p["list_price"] - unit) * qty, 2)}
    if matched_unit is not None and matched_unit < unit:
        line.update(unit_price=matched_unit, line_total=round(matched_unit * qty, 2), member_unit_price=unit,
                    savings=round((p["list_price"] - matched_unit) * qty, 2), price_matched=True)
    return line


def _normalize_lines(s: dict, lines, match: dict | None = None) -> list[dict]:
    if not isinstance(lines, list) or not lines:
        raise ToolError("An order needs at least one item")
    merged: dict[str, int] = {}
    for ln in lines:
        if not isinstance(ln, dict) or not ln.get("sku"):
            raise ToolError("Each line needs a sku and qty")
        merged[ln["sku"]] = merged.get(ln["sku"], 0) + int(ln.get("qty") or 1)
    return [_line(s, sku, qty, (match or {}).get(sku)) for sku, qty in merged.items()]


def _option(s: dict, delivery_option: str) -> str:
    option = delivery_option or s["delivery"].get("default_option") or C.DELIVERY_OPTIONS[1]
    if option not in C.DELIVERY_OPTIONS:
        raise ToolError(f"Delivery option must be one of: {', '.join(C.DELIVERY_OPTIONS)}")
    return option


def _totals(s: dict, lines: list[dict], option: str) -> dict:
    """Same arithmetic the phone runs offline (mobile/app/cart.tsx)."""
    tier = C.TIER_BY_CODE[s["membership"]["tier"]]
    subtotal = round(sum(l["line_total"] for l in lines), 2)
    fee = 0.0 if option == C.PICKUP_OPTION or subtotal >= tier["free_delivery_min_usd"] else C.DELIVERY_FEE_USD
    tax = round(subtotal * C.TAX_RATE, 2)
    total = round(subtotal + fee + tax, 2)
    credit = round(min(float(s["wallet"].get("store_credit_usd", 0)), total), 2)
    return {"subtotal_usd": subtotal, "delivery_fee_usd": fee, "tax_usd": tax, "total_usd": total,
            "savings_usd": round(sum(l["savings"] for l in lines), 2), "store_credit_applied_usd": credit,
            "amount_due_usd": round(total - credit, 2), "points_earned": int(subtotal) * tier["points_per_usd"]}


def wallet_view(s: dict) -> dict:
    w = s["wallet"]
    return {"store_credit_usd": round(float(w.get("store_credit_usd", 0)), 2), "points": int(w.get("points", 0)),
            "payment_method": w.get("payment_method"), "tier": s["membership"]["tier"],
            "tier_name": s["membership"]["tier_name"], "discount_pct": s["membership"]["discount_pct"]}


def limit_check(s: dict, lines: list[dict]) -> list[dict]:
    """High-demand items carry a per-household limit over a rolling window."""
    out = []
    for l in lines:
        limit = C.PRODUCT_BY_SKU[l["sku"]].get("limit_per_household")
        if not limit:
            continue
        bought = sum(x["qty"] for o in s.get("order_history", []) for x in o.get("lines", [])
                     if x["sku"] == l["sku"] and (days_since(o.get("date")) or 0) <= C.PURCHASE_LIMIT_WINDOW_DAYS)
        if bought + l["qty"] > limit:
            out.append({"sku": l["sku"], "name": l["name"], "limit": limit, "already_bought": bought, "requested": l["qty"],
                        "window_days": C.PURCHASE_LIMIT_WINDOW_DAYS})
    return out


def _eta(option: str) -> str:
    days = 1 if option == C.SCHEDULED_OPTION else 0
    return (today() + dt.timedelta(days=days)).isoformat()


def delivery_plan(s: dict, option: str, order_id: str) -> dict:
    """How this order reaches the door: the hub it leaves from, the courier,
    the window and the customer's drop-off instructions. It is written onto
    the order, so the phone shows it from Couchbase Lite with no signal."""
    hub = s.get("home_hub") or {}
    hub_id = hub.get("hub_id")
    dl = s.get("delivery", {})
    window = dl.get("preferred_window") or C.preferred_window(s["customer_id"])
    plan = {"option": option, "hub": hub.get("name"), "date": _eta(option), "stage": "packing",
            "drop_off": (dl.get("notes") or "").strip() or None,
            "address": ", ".join(x for x in [s.get("address", {}).get("street"), s.get("address", {}).get("city")] if x)}
    if option == C.PICKUP_OPTION:
        mins = C.hub_doc_body(hub_id)["pickup_ready_minutes"] if hub_id in C.HUBS else 120
        return {**plan, "eta_minutes": mins, "window": f"Ready in about {mins} min", "courier": None, "drop_off": None}
    courier = C.courier_for(hub_id, order_id)
    if option == C.EXPRESS_OPTION:
        mins = C.express_minutes(hub_id)
        return {**plan, "eta_minutes": mins, "window": f"In about {mins} min", "courier": courier}
    day = "Tomorrow" if option == C.SCHEDULED_OPTION else "Today"
    return {**plan, "eta_minutes": None, "window": f"{day}, {window}", "courier": courier}


def _next_order_id(s: dict) -> str:
    return f"CD-{today():%y%m%d}-{_h(s['customer_id'], now_iso(), uuid.uuid4().hex) % 90000 + 10000}"


# --------------------------------------------------------------------------
# read-only tools
# --------------------------------------------------------------------------
async def get_customer_context(customer_id: str) -> dict:
    s = await load_customer(customer_id)
    last = s["order_history"][0] if s.get("order_history") else None
    return {
        "customer_id": customer_id, "first_name": s["first_name"], "household": s.get("household"),
        "membership": s["membership"], "wallet": wallet_view(s), "delivery": s["delivery"], "home_hub": s.get("home_hub"),
        "preferences": s.get("preferences", {}), "last_order": last,
        "days_since_last_order": days_since(last["date"]) if last else None,
        "spend": s.get("spend", {}), "subscriptions": s.get("subscriptions", []), "returns": s.get("returns", [])[:3],
        "segment": s["ml_scores"].get("segment"), "next_best_offer": s["ml_scores"].get("next_best_offer"),
    }


async def get_recommendations(customer_id: str) -> dict:
    """The model's smart cart for this customer (what is about to run out),
    member priced and checked against the fulfilling center's on-hand units,
    plus the 'for you' picks and any price-match candidates."""
    from . import personalization
    s = await load_customer(customer_id)
    recs = await personalization.compute_recommendations(s)
    lines = [l for l in recs["lines"] if l["selected"]]
    option = _option(s, "")
    tot = _totals(s, [{**l, "savings": round((l["list_price"] - l["unit_price"]) * l["qty"], 2)} for l in lines], option) if lines else {}
    return {"customer_id": customer_id, "tier": s["membership"]["tier"], "tier_name": s["membership"]["tier_name"],
            "fulfillment_center": s["delivery"]["fulfillment_center"], "delivery_option": option,
            "lines": lines, "totals": tot, "wallet": wallet_view(s), "for_you": recs["for_you"],
            "price_matches": recs["price_matches"], "model_version": s["ml_scores"].get("model_version")}


async def search_catalog(customer_id: str, query: str = "", category: str = "") -> dict:
    s = await load_customer(customer_id)
    inv, _ = await get_inventory(s["delivery"]["fulfillment_center"])
    hub_id = (s.get("home_hub") or {}).get("hub_id")
    q = (query or "").lower().split()
    out = []
    for p in C.PRODUCTS:
        if category and p["category"] != category:
            continue
        hay = f"{p['name']} {p['sku']} {' '.join(p['tags'])} {C.CATEGORIES[p['category']]['name']}".lower()
        score = sum(1 for w in q if w in hay)
        if q and not score:
            continue
        rep = s.get("replenishment", {}).get(p["sku"])
        out.append({**_line(s, p["sku"], 1), "on_hand_at_fc": inv["on_hand"].get(p["sku"], 0),
                    "bay": C.bay_for(hub_id, p["sku"]) if hub_id in C.HUBS else None,
                    "buys_regularly": bool(rep), "avg_monthly_qty": (rep or {}).get("avg_monthly_qty"),
                    "limit_per_household": p.get("limit_per_household"), "score": score + (0.5 if rep else 0)})
    out.sort(key=lambda r: (-r["score"], r["name"]))
    return {"customer_id": customer_id, "items": out[:15]}


async def quote_cart(customer_id: str, lines: list, delivery_option: str = "") -> dict:
    s = await load_customer(customer_id)
    ls = _normalize_lines(s, lines)
    option = _option(s, delivery_option)
    inv, _ = await get_inventory(s["delivery"]["fulfillment_center"])
    short_lines = [{"sku": l["sku"], "name": l["name"], "requested": l["qty"], "on_hand": inv["on_hand"].get(l["sku"], 0)}
                   for l in ls if inv["on_hand"].get(l["sku"], 0) < l["qty"]]
    return {"customer_id": customer_id, "lines": ls, "totals": _totals(s, ls, option), "delivery_option": option,
            "wallet": wallet_view(s), "short": short_lines, "purchase_limits": limit_check(s, ls),
            "fulfillment_center": s["delivery"]["fulfillment_center"]}


# --------------------------------------------------------------------------
# mutating tools
# --------------------------------------------------------------------------
async def place_order(customer_id: str, lines: list, delivery_option: str = "", notes: str = "",
                      _match: dict | None = None) -> dict:
    s = await load_customer(customer_id)
    ls = _normalize_lines(s, lines, _match)
    option = _option(s, delivery_option)
    over = limit_check(s, ls)
    if over:
        o = over[0]
        return {"ok": False, "status": "failed", "reason_code": "purchase_limit", "purchase_limits": over,
                "summary": f"{short(o['name'])} is limited to {o['limit']} per household every {o['window_days']} days, and "
                           f"your household bought {o['already_bought']} in that window. Remove it to place the rest of the order."}
    tot = _totals(s, ls, option)

    fc = s["delivery"]["fulfillment_center"]
    got = await allocate_inventory(fc, {l["sku"]: l["qty"] for l in ls})
    backordered = []
    for l in ls:
        l["shipped_qty"] = got[l["sku"]]
        l["backordered_qty"] = l["qty"] - got[l["sku"]]
        if l["backordered_qty"]:
            backordered.append({"sku": l["sku"], "name": l["name"], "qty": l["backordered_qty"],
                                "eta": (today() + dt.timedelta(days=5 + _h(fc, l["sku"]) % 6)).isoformat()})
    order_id = _next_order_id(s)
    status = "partially_shipped" if backordered else "confirmed"
    hub_name = (s.get("home_hub") or {}).get("name")
    order = {"order_id": order_id, "date": today().isoformat(), "placed_at": now_iso(), "status": status,
             "channel": "app", "delivery_option": option, "eta": _eta(option), "fulfillment_center": fc,
             "pickup_hub": hub_name if option == C.PICKUP_OPTION else None, "notes": (notes or "").strip()[:300],
             "delivery": delivery_plan(s, option, order_id),
             "lines": ls, "line_count": len(ls), **tot, "backordered": backordered, "price_match": bool(_match)}
    # live state on the customer: wallet, history, replenishment
    w = s["wallet"]
    w["store_credit_usd"] = round(float(w.get("store_credit_usd", 0)) - tot["store_credit_applied_usd"], 2)
    w["points"] = int(w.get("points", 0)) + tot["points_earned"]
    s["order_history"] = ([order] + s.get("order_history", []))[:24]
    for l in ls:
        if C.PRODUCT_BY_SKU[l["sku"]]["consumable"]:
            r = s.setdefault("replenishment", {}).setdefault(l["sku"], {"avg_monthly_qty": l["qty"]})
            r["last_ordered"] = today().isoformat()
            r["last_qty"] = l["qty"]
    sp = s.setdefault("spend", {})
    sp["ytd_usd"] = round(sp.get("ytd_usd", 0) + tot["total_usd"], 2)
    sp["orders_last_12mo"] = sp.get("orders_last_12mo", 0) + 1
    await save_customer(s)
    await after_change(customer_id)
    bo = (f" {len(backordered)} item{'s' if len(backordered) > 1 else ''} backordered: "
          + "; ".join(f"{short(b['name'])} x{b['qty']} (ETA {b['eta']})" for b in backordered) + ".") if backordered else ""
    plan = order["delivery"]
    where = (f"Pickup at {hub_name}, {plan['window'].lower()}" if option == C.PICKUP_OPTION
             else f"{option} from {hub_name}: {plan['window'][0].lower() + plan['window'][1:]} with {plan['courier']['name']} "
                  f"({plan['courier']['vehicle']})" + (f". Drop-off: {plan['drop_off']}" if plan["drop_off"] else ""))
    credit = f" {money(tot['store_credit_applied_usd'])} store credit applied." if tot["store_credit_applied_usd"] else ""
    return {"ok": True, "status": status, "charge_usd": tot["amount_due_usd"], "item": order,
            "summary": f"Order {order_id} placed: {len(ls)} item{'s' if len(ls) > 1 else ''}, {money(tot['total_usd'])} "
                       f"({money(tot['savings_usd'])} saved, {tot['points_earned']} points earned).{credit} {where}.{bo}"}


async def request_price_match(customer_id: str, lines: list, sku: str, competitor: str, competitor_price_usd: float,
                              delivery_option: str = "", notes: str = "") -> dict:
    """Place an order with one item matched to a competitor's lower price.
    Held for a Customer Care decision in AOM's approval tier before it can
    run; once approved the item is re-priced and the order is placed."""
    s = await load_customer(customer_id)
    ls = _normalize_lines(s, lines)
    line = next((l for l in ls if l["sku"] == sku), None)
    if not line:
        raise ToolError(f"{sku} isn't in this order, so there is nothing to match")
    if competitor not in C.COMPETITORS:
        raise ToolError(f"We price match {', '.join(C.COMPETITORS)}")
    price = round(float(competitor_price_usd), 2)
    if price >= line["unit_price"]:
        # Nothing to match: our member price is already as low. Just place it.
        return await place_order(customer_id, lines, delivery_option, notes)
    floor = round(line["list_price"] * C.PRICE_MATCH_FLOOR_PCT / 100.0, 2)
    if price < floor:
        raise ToolError(f"A matched price can't go below {money(floor)} for {short(line['name'])} "
                        f"({C.PRICE_MATCH_FLOOR_PCT}% of list)")
    saving = round((line["unit_price"] - price) * line["qty"], 2)
    if saving > C.PRICE_MATCH_MAX_SAVING_USD:
        raise ToolError(f"Price matches are capped at {money(C.PRICE_MATCH_MAX_SAVING_USD)} per order")
    res = await place_order(customer_id, lines, delivery_option,
                            notes or f"Price match: {competitor} at {money(price)}", _match={sku: price})
    if res.get("ok"):
        res["summary"] = (f"Price match applied: {short(line['name'])} at {competitor}'s {money(price)}, saving {money(saving)}. "
                          + res["summary"])
        res["item"]["price_match"] = {"sku": sku, "competitor": competitor, "matched_price_usd": price, "saved_usd": saving}
    return res


async def set_subscription(customer_id: str, sku: str, qty: int, cadence_weeks: int = 4) -> dict:
    s = await load_customer(customer_id)
    ln = _line(s, sku, qty)
    if not C.PRODUCT_BY_SKU[sku]["consumable"]:
        raise ToolError("Subscribe & Save is for everyday essentials you reorder, not one-time purchases")
    cadence = int(cadence_weeks)
    if cadence not in (1, 2, 4, 6, 8, 12):
        raise ToolError("Cadence must be 1, 2, 4, 6, 8 or 12 weeks")
    sub = {"sku": sku, "name": ln["name"], "qty": ln["qty"], "unit_price": ln["unit_price"], "cadence_weeks": cadence,
           "next_date": (today() + dt.timedelta(weeks=cadence)).isoformat(), "created_at": now_iso()}
    s["subscriptions"] = [x for x in s.get("subscriptions", []) if x["sku"] != sku] + [sub]
    await save_customer(s)
    await after_change(customer_id)
    return {"ok": True, "status": "confirmed", "charge_usd": 0, "item": {**sub, "kind": "subscription"},
            "summary": f"Subscribe & Save set: {ln['qty']} x {short(ln['name'])} every {cadence} week"
                       f"{'s' if cadence > 1 else ''} at {money(ln['unit_price'])}, next on {sub['next_date']}."}


async def create_return(customer_id: str, order_id: str, sku: str, qty: int, reason: str) -> dict:
    s = await load_customer(customer_id)
    order = next((o for o in s.get("order_history", []) if o.get("order_id") == order_id), None)
    if not order:
        raise ToolError(f"Order {order_id} isn't in your recent orders")
    if (days_since(order["date"]) or 0) > C.RETURN_WINDOW_DAYS:
        raise ToolError(f"Returns are accepted within {C.RETURN_WINDOW_DAYS} days of delivery")
    line = next((l for l in order.get("lines", []) if l["sku"] == sku), None)
    if not line:
        raise ToolError(f"{sku} wasn't on order {order_id}")
    qty = int(qty)
    already = sum(r["qty"] for r in s.get("returns", []) if r["order_id"] == order_id and r["sku"] == sku)
    if qty < 1 or qty + already > line["qty"]:
        raise ToolError(f"Return quantity must be between 1 and {line['qty'] - already}")
    if not reason or len(reason.strip()) < 3:
        raise ToolError("A return needs a reason")
    refund = round(line["unit_price"] * qty, 2)
    hub_name = (s.get("home_hub") or {}).get("name") or "any Couchbase Delivery store"
    rma = {"return_id": f"RTN-{_h(order_id, sku, now_iso()) % 900000 + 100000}", "order_id": order_id, "sku": sku,
           "name": line["name"], "qty": qty, "refund_usd": refund, "reason": reason.strip()[:200], "date": today().isoformat(),
           "drop_off": hub_name, "kind": "return"}
    s["wallet"]["store_credit_usd"] = round(float(s["wallet"].get("store_credit_usd", 0)) + refund, 2)
    s["returns"] = ([rma] + s.get("returns", []))[:12]
    await save_customer(s)
    await after_change(customer_id)
    return {"ok": True, "status": "confirmed", "charge_usd": -refund, "item": rma,
            "summary": f"{rma['return_id']} created: {qty} x {short(line['name'])} from {order_id}. {money(refund)} is in your "
                       f"store credit now. Hand it to your next courier, or drop it at {hub_name}, within 14 days."}


async def update_preferences(customer_id: str, favorite_categories: list | None = None, avoid_categories: list | None = None,
                             default_delivery_option: str = "", allow_substitutions: bool | None = None,
                             delivery_notes: str | None = None, preferred_window: str = "") -> dict:
    """What the customer wants more or less of, and how they want it
    delivered: default option, window and drop-off instructions. Changes how
    the recommendations are ranked on the next sync, and what the courier is
    told on the next order."""
    s = await load_customer(customer_id)
    prefs = s.setdefault("preferences", {})
    for name, value in (("favorite_categories", favorite_categories), ("avoid_categories", avoid_categories)):
        if value is None:
            continue
        bad = [c for c in value if c not in C.CATEGORIES]
        if bad:
            raise ToolError(f"Unknown categor{'ies' if len(bad) > 1 else 'y'}: {', '.join(bad)}")
        prefs[name] = sorted(set(value))
    clash = set(prefs.get("favorite_categories", [])) & set(prefs.get("avoid_categories", []))
    if clash:
        raise ToolError(f"{C.CATEGORIES[sorted(clash)[0]]['name']} can't be both a favorite and hidden")
    if default_delivery_option:
        s["delivery"]["default_option"] = _option(s, default_delivery_option)
    if allow_substitutions is not None:
        prefs["allow_substitutions"] = bool(allow_substitutions)
    if delivery_notes is not None:
        s["delivery"]["notes"] = str(delivery_notes).strip()[:200]
    if preferred_window:
        if preferred_window not in C.DELIVERY_WINDOWS:
            raise ToolError(f"Delivery window must be one of: {', '.join(C.DELIVERY_WINDOWS)}")
        s["delivery"]["preferred_window"] = preferred_window
    prefs["updated_at"] = now_iso()
    await save_customer(s)
    await after_change(customer_id)
    fav = ", ".join(C.CATEGORIES[c]["name"] for c in prefs.get("favorite_categories", [])) or "none"
    hide = ", ".join(C.CATEGORIES[c]["name"] for c in prefs.get("avoid_categories", [])) or "none"
    return {"ok": True, "status": "confirmed", "charge_usd": 0,
            "item": {"kind": "preferences", **{k: v for k, v in prefs.items()}, "default_delivery_option": s["delivery"].get("default_option"),
                     "preferred_window": s["delivery"].get("preferred_window"), "delivery_notes": s["delivery"].get("notes")},
            "summary": f"Preferences saved. More of: {fav}. Hidden: {hide}. Default delivery: "
                       f"{s['delivery'].get('default_option')}, {s['delivery'].get('preferred_window') or 'any'} window"
                       + (f", drop-off: {s['delivery']['notes']}" if s["delivery"].get("notes") else "")
                       + ". Your recommendations have been re-ranked."}


async def issue_goodwill_credit(customer_id: str, amount_usd: float, reason: str) -> dict:
    """A goodwill store credit (damaged delivery, missed window). Held for a
    human decision in AOM's approval tier before it is applied."""
    s = await load_customer(customer_id)
    amt = round(float(amount_usd), 2)
    if amt <= 0 or amt > C.GOODWILL_MAX_USD:
        raise ToolError(f"Goodwill credits are between $0.01 and {money(C.GOODWILL_MAX_USD)}")
    if not reason or len(reason.strip()) < 5:
        raise ToolError("A goodwill credit needs a reason for the audit trail")
    s["wallet"]["store_credit_usd"] = round(float(s["wallet"].get("store_credit_usd", 0)) + amt, 2)
    item = {"kind": "goodwill_credit", "credit_id": f"GC-{_h(customer_id, now_iso()) % 900000 + 100000}", "amount_usd": amt,
            "reason": reason.strip()[:200], "date": today().isoformat()}
    s["credits"] = ([item] + s.get("credits", []))[:12]
    await save_customer(s)
    await after_change(customer_id)
    return {"ok": True, "status": "confirmed", "charge_usd": -amt, "item": item,
            "summary": f"Goodwill credit of {money(amt)} added to your store credit - it comes off your next order "
                       f"automatically. Reason recorded: {reason.strip()[:120]}"}


TOOLS = {
    "get_customer_context": get_customer_context,
    "get_recommendations": get_recommendations,
    "search_catalog": search_catalog,
    "quote_cart": quote_cart,
    "place_order": place_order,
    "request_price_match": request_price_match,
    "set_subscription": set_subscription,
    "create_return": create_return,
    "update_preferences": update_preferences,
    "issue_goodwill_credit": issue_goodwill_credit,
}
READ_ONLY_TOOLS = {"get_customer_context", "get_recommendations", "search_catalog", "quote_cart"}
APPROVAL_TOOLS = ["request_price_match", "issue_goodwill_credit"]
