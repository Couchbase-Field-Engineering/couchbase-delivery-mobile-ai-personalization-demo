"""Knowledge Base documents published to AOM by the daily loader.

Two kinds:

* **Customer profile** - one per recently active customer, rendered from that
  morning's Databricks row as plain prose. The assistant retrieves it with a
  `document_id`-scoped search, so a question from one customer can only ever
  be grounded in *their own* profile, never another customer's that happens to
  be semantically close.
* **Delivery Guide** - membership, pricing, delivery, returns, price match
  and purchase-limit policy. Contains no customer data, so answers grounded
  only in it are safe to share across customers through AOM's LLM cache.

FAQ entries are also synced to the phone inside the catalog document, so the
app can answer the common questions offline from Couchbase Lite.
"""
from __future__ import annotations

from . import catalog as C

FAQ = [
    {"q": "How does member pricing work?",
     "a": "Delivery Pass has three tiers: Member (free, list price, 1 point per dollar), Plus (5% off every item, 2 points "
          "per dollar) and Premier (10% off, 3 points per dollar). Multi-buy savings stack on top: 3 or more of the same item "
          "takes another 5% off, 6 or more another 10%. The app prices every item from your tier on the phone, so the total "
          "is right with or without signal.",
     "keywords": ["member", "pricing", "price", "discount", "tier", "plus", "premier", "multi-buy", "membership", "points"]},
    {"q": "What are the delivery options?",
     "a": "Express delivery (a courier leaves your local hub right away, usually 25 to 55 minutes door to door), Same-day "
          "delivery in a two-hour window, Scheduled delivery in tomorrow's window, and Hub pickup. Delivery is free on every "
          "Plus and Premier order and on Member orders over $35 (otherwise $5.99). Hub pickup is always free and is usually "
          "ready in about two hours at your home hub. The app picks the window you are usually home for; change it, and your "
          "drop-off instructions, in My preferences.",
     "keywords": ["delivery", "deliver", "ship", "shipping", "same-day", "express", "window", "courier", "pickup", "pick up",
                  "arrive", "when will", "eta", "fee", "drop-off", "drop off", "instructions"]},
    {"q": "What happens when an item is out of stock?",
     "a": "The order still goes through. Available units go out with your courier and the rest is backordered with an "
          "ETA on the order confirmation; you are only charged for what is delivered. The app shows how many are on hand next to "
          "each item so you can pick something else before you check out.",
     "keywords": ["out of stock", "backorder", "stock", "available", "availability", "on hand", "substitute", "sold out"]},
    {"q": "How does a price match work?",
     "a": "If Brightway Market, Northfield Supply or Oakline Stores has the identical item for less than your member price, "
          "check out with a price match request. Customer Care reviews it in the Agent Operations Manager; once approved the "
          "item is re-priced and the order is placed automatically. A matched price can't go below 70% of list and a match "
          "saves at most $150 per order.",
     "keywords": ["price match", "match", "cheaper", "competitor", "lower price", "beat", "found it for less"]},
    {"q": "What is the returns policy?",
     "a": "Most items can be returned within 30 days of delivery. Start the return in the app and the refund lands in your "
          "store credit right away; hand the item to your next courier or drop it at any hub within 14 days. "
          "Damaged-on-arrival items can be credited without a return - ask the assistant for a goodwill credit.",
     "keywords": ["return", "returns", "refund", "damaged", "wrong item", "send back", "exchange"]},
    {"q": "How does Subscribe & Save work?",
     "a": "Put any everyday essential on a schedule: a fixed quantity every 1, 2, 4, 6, 8 or 12 weeks at your member price, "
          "delivered with your default delivery option. Pause or change it any time. Subscribed items are left out of your "
          "smart cart so you never double up.",
     "keywords": ["subscribe", "subscription", "recurring", "auto", "schedule", "every week", "every month", "cadence", "save"]},
    {"q": "How are my recommendations chosen?",
     "a": "Each night the next-basket model in Databricks looks at what you buy, how quickly you go through it and what "
          "customers like you add next, and writes a smart cart and a set of picks with a confidence for each. The daily "
          "export lands in Couchbase and syncs to your phone, where it is re-priced at your member tier and checked against "
          "stock. Every order and every preference you change re-ranks it on the next sync.",
     "keywords": ["recommend", "recommendation", "smart cart", "for you", "model", "why", "personalized", "suggest", "databricks"]},
    {"q": "Why can't I buy more than one of an item?",
     "a": "High-demand items such as the Nova X handheld console are limited to one per household every 30 days so more "
          "customers get a chance to buy one. An order that goes over the limit is not placed; remove the item and the rest "
          "of your cart checks out normally. Premier members get early access to limited releases, not a higher limit.",
     "keywords": ["limit", "limited", "one per", "more than one", "second", "restricted", "console", "household"]},
    {"q": "What can I do in the app with no signal?",
     "a": "Everything you need to order: browse the catalog, see your smart cart and picks, check your delivery window and "
          "drop-off instructions, build and price a cart, and check out. The order is saved to Couchbase Lite on your phone as 'On device' and "
          "syncs through Sync Gateway the moment you have a connection - at the top of the subway stairs, in the parking lot "
          "or back on Wi-Fi. Confirmations, the courier and delivery window, backorders and approvals come back to the same "
          "order card.",
     "keywords": ["signal", "offline", "no service", "connection", "wifi", "sync", "subway", "airplane", "garage"]},
    {"q": "How do store credit and points work?",
     "a": "Refunds and goodwill credits go to your store credit, which comes off your next order automatically. Points are "
          "earned on every order's subtotal at your tier's rate and show in your wallet after the order confirms. Goodwill "
          "credits up to $100 can be requested for a service problem and always need Customer Care approval.",
     "keywords": ["store credit", "credit", "points", "wallet", "rewards", "goodwill", "balance", "gift"]},
    {"q": "What if my delivery is late, damaged or missing something?",
     "a": "Tell the assistant what happened. A damaged or missing item can be credited without a return, and a delivery that "
          "misses its window qualifies for a goodwill credit of up to $100. Every goodwill credit is reviewed by Customer Care "
          "in the Agent Operations Manager, then lands in your store credit and comes off your next order.",
     "keywords": ["late", "missed the window", "never arrived", "missing item", "damaged", "crushed", "melted", "wrong item"]},
    {"q": "How do drop-off instructions and delivery windows work?",
     "a": "Your drop-off instructions (side door, concierge, gate code) and the two-hour window you are usually home for are "
          "part of your profile. They sync to your phone, are attached to every order you place - even one placed with no "
          "signal - and are what your courier sees. Change them in My preferences; the change is saved on the phone and applied "
          "when it syncs.",
     "keywords": ["drop-off", "drop off", "instructions", "gate code", "side door", "concierge", "window", "leave it", "doorstep"]},
]


def guide_markdown(export_date: str) -> str:
    lines = [f"# Couchbase Delivery Guide (published {export_date})", "",
             "Membership, pricing, delivery options and windows, returns, price match and purchase-limit knowledge for the "
             "Couchbase Delivery assistant. Contains no customer data.", ""]
    lines += ["## Frequently asked questions", ""]
    for f in FAQ:
        lines += [f"**{f['q']}** {f['a']}", ""]
    lines += ["## Delivery Pass tiers", ""]
    for t in C.MEMBER_TIERS:
        lines.append(f"- {t['name']} ({t['code']}): {t['discount_pct']}% off list, {t['points_per_usd']} point"
                     f"{'s' if t['points_per_usd'] > 1 else ''} per dollar, free delivery "
                     + ("on every order" if t["free_delivery_min_usd"] == 0 else f"over ${t['free_delivery_min_usd']}") + f". {t['blurb']}")
    lines += ["", "Multi-buy savings on a single item: " + ", ".join(f"{q}+ units an extra {e}%" for q, e in C.MULTI_BUY)
              + f". Delivery fee when not free: ${C.DELIVERY_FEE_USD}. Options: {', '.join(C.DELIVERY_OPTIONS)}. "
              f"{C.PICKUP_OPTION} is always free. Delivery windows: {', '.join(C.DELIVERY_WINDOWS)}.", ""]
    lines += ["## Price match, credits and limits", "",
              f"Couchbase Delivery matches {', '.join(C.COMPETITORS)} on identical items. A match needs Customer Care approval, can't go "
              f"below {C.PRICE_MATCH_FLOOR_PCT}% of list and saves at most ${C.PRICE_MATCH_MAX_SAVING_USD:,.0f} per order. Refunds "
              f"and goodwill credits (up to ${C.GOODWILL_MAX_USD:,.0f}, approval required) go to store credit and come off the "
              f"next order. Returns are accepted within {C.RETURN_WINDOW_DAYS} days. Limited items are restricted per household "
              f"over a rolling {C.PURCHASE_LIMIT_WINDOW_DAYS} days.", ""]
    lines += ["## Products", ""]
    for code, cat in C.CATEGORIES.items():
        items = [p for p in C.PRODUCTS if p["category"] == code]
        if not items:
            continue
        lines.append(f"### {cat['name']}")
        for p in items:
            lines.append(f"- {p['name']} ({p['sku']}): ${p['list_price']} list per {p['uom']}, {p['pack']}"
                         + ("; everyday essential, eligible for Subscribe & Save." if p["consumable"] else "; one-time purchase.")
                         + (f" Limit {p['limit_per_household']} per household." if p.get("limit_per_household") else ""))
        lines.append("")
    lines += ["## Fulfillment centers", ""]
    for code, fc in C.FULFILLMENT_CENTERS.items():
        lines.append(f"- {fc['name']} ({code}), {fc['city']}: stocks hubs in {', '.join(fc['states'])}.")
    lines += ["", "## Hubs", "",
              f"{len(C.HUBS)} local delivery hubs across " + ", ".join(r["name"] for r in C.REGIONS.values())
              + ". Couriers leave from the customer's home hub. Every hub offers Express delivery, a pickup counter and "
              "returns drop-off."]
    return "\n".join(lines)


def customer_profile_markdown(s: dict) -> str:
    m = s["ml_scores"]
    w = s["wallet"]
    hist = s.get("order_history", [])[:6]
    hist_txt = "; ".join(f"{o['order_id']} on {o['date']} ${o['total_usd']:,.2f} ({o.get('line_count', len(o.get('lines', [])))} items, "
                         f"{o.get('delivery_option', 'delivery')})" for o in hist) or "no orders yet"
    rep = sorted(s.get("replenishment", {}).items(), key=lambda kv: -float(kv[1].get("avg_monthly_qty") or 0))[:8]
    rep_txt = "; ".join(f"{C.PRODUCT_BY_SKU[sku]['name'].split(',')[0]} ~{v.get('avg_monthly_qty', 0):g} "
                        f"{C.PRODUCT_BY_SKU[sku]['uom']}/month, last {v.get('last_ordered')}" for sku, v in rep if sku in C.PRODUCT_BY_SKU)
    cart = "; ".join(f"{int(l['qty'])} x {C.PRODUCT_BY_SKU[l['sku']]['name'].split(',')[0]} ({l.get('confidence', 0):.0%})"
                     for l in m.get("replenish_lines", []) if l["sku"] in C.PRODUCT_BY_SKU)
    picks = "; ".join(f"{C.PRODUCT_BY_SKU[r['sku']]['name'].split(',')[0]} ({r.get('reason')})"
                      for r in m.get("recommended", []) if r["sku"] in C.PRODUCT_BY_SKU) or "none"
    watch = "; ".join(f"{C.PRODUCT_BY_SKU[x['sku']]['name'].split(',')[0]} at {x['competitor']} for ${x['competitor_price_usd']:,.2f}"
                      for x in m.get("price_watch", []) if x["sku"] in C.PRODUCT_BY_SKU) or "none"
    subs = "; ".join(f"{x['qty']} x {x['name'].split(',')[0]} every {x['cadence_weeks']}w" for x in s.get("subscriptions", [])) or "none"
    prefs = s.get("preferences", {})
    hh = s.get("household", {})
    store = s.get("home_hub") or {}
    return "\n".join([
        f"# Customer profile {s['customer_id']}: {s['first_name']} {s['last_name'][:1]}.",
        f"Source: Databricks daily export {s['export_date']}, model {m.get('model_version')}.",
        "",
        "## Customer",
        f"{s['first_name']} orders from {s['address']['city']}, {s['address']['state']} and is a {hh.get('type_name', 'household').lower()} "
        f"of {hh.get('size', 1)}" + (f" with {', '.join(hh['pets'])}" if hh.get("pets") else "") + ". "
        f"Home hub: {store.get('name')}, stocked by {C.FULFILLMENT_CENTERS[s['delivery']['fulfillment_center']]['name']}. "
        f"Default delivery: {s['delivery'].get('default_option')}. Usual delivery window: "
        f"{s['delivery'].get('preferred_window') or 'none learned yet'}. Drop-off instructions: {s['delivery'].get('notes') or 'none'}. "
        f"Connectivity: {s.get('engagement', {}).get('connectivity_note')}.",
        "",
        "## Membership and wallet",
        f"{s['membership']['tier_name']} member since {s['membership'].get('member_since')} ({s['membership']['discount_pct']}% off list), "
        f"renews {s['membership'].get('renewal_date') or 'n/a'}. Store credit ${float(w.get('store_credit_usd', 0)):,.2f}, "
        f"{int(w.get('points', 0)):,} points. Pays with {w.get('payment_method')}.",
        "",
        "## Orders and replenishment",
        f"Spend last 12 months ${s.get('spend', {}).get('last_12mo_usd', 0):,.0f} over {s.get('spend', {}).get('orders_last_12mo', 0)} orders, "
        f"average order ${s.get('spend', {}).get('avg_order_usd', 0):,.0f}. Recent orders: {hist_txt}.",
        f"Goes through: {rep_txt}.",
        f"Subscribe & Save: {subs}.",
        "",
        "## Preferences",
        f"Wants more of: {', '.join(C.CATEGORIES[c]['name'] for c in prefs.get('favorite_categories', []) if c in C.CATEGORIES) or 'no favorites set'}. "
        f"Hidden: {', '.join(C.CATEGORIES[c]['name'] for c in prefs.get('avoid_categories', []) if c in C.CATEGORIES) or 'nothing'}. "
        f"Substitutions {'allowed' if prefs.get('allow_substitutions', True) else 'not allowed'}.",
        "",
        "## Recommendations",
        f"Segment: {m.get('segment')}. Next best offer: {m.get('next_best_offer')}. Churn risk {m.get('churn_risk')}. "
        f"Predicted basket ${m.get('predicted_basket_usd', 0):,.0f}. Smart cart: {cart or 'nothing due'}. "
        f"Picks: {picks}. Price watch: {watch}.",
    ])
