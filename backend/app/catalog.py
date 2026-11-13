"""Reference catalog for the demo: what Couchbase Delivery brings to the door,
member pricing tiers, delivery options and windows, the fulfillment centers
that stock orders and the local hubs couriers deliver from.

This is the single source of truth shared by the Databricks mock-dump
generator (databricks/generate_mock_dump.py imports it), the backend's
recommendation engine and the MCP tools. Couchbase Delivery is a fictional delivery service:
products, brands, prices, hubs, couriers and competitor names are invented for the
demo.
"""
from __future__ import annotations

import hashlib

# --------------------------------------------------------------------------
# Product categories. `affinity` names the model score that drives how
# strongly a category is recommended to a customer.
# --------------------------------------------------------------------------
CATEGORIES = {
    "pantry": {"name": "Pantry & grocery", "affinity": "pantry_affinity", "icon": "basket"},
    "household": {"name": "Household essentials", "affinity": "household_affinity", "icon": "home"},
    "personal": {"name": "Personal care", "affinity": "personal_affinity", "icon": "water"},
    "baby": {"name": "Baby", "affinity": "baby_affinity", "icon": "happy"},
    "pets": {"name": "Pets", "affinity": "pets_affinity", "icon": "paw"},
    "kitchen": {"name": "Home & kitchen", "affinity": "kitchen_affinity", "icon": "restaurant"},
    "electronics": {"name": "Electronics", "affinity": "electronics_affinity", "icon": "headset"},
    "toys": {"name": "Toys & games", "affinity": "toys_affinity", "icon": "game-controller"},
    "outdoor": {"name": "Sports & outdoors", "affinity": "outdoor_affinity", "icon": "bicycle"},
}

# SKU, name, category, unit of measure, list price (USD), pack size, search
# tags, and whether it is a consumable the replenishment model tracks.
# `limit_per_household` marks a high-demand item with a purchase limit.
PRODUCTS = [
    # pantry & grocery
    {"sku": "CD-110245", "name": "Morning Ridge Medium Roast Coffee Pods, 72-count", "category": "pantry", "uom": "box",
     "list_price": 34.99, "pack": "72 pods", "tags": ["coffee", "pods", "breakfast"], "consumable": True},
    {"sku": "CD-110388", "name": "Golden Field Rolled Oats, 42 oz, 2-pack", "category": "pantry", "uom": "pack",
     "list_price": 9.49, "pack": "2 canisters", "tags": ["breakfast", "oatmeal"], "consumable": True},
    {"sku": "CD-110512", "name": "Casa Verde Extra Virgin Olive Oil, 1 L", "category": "pantry", "uom": "bottle",
     "list_price": 14.99, "pack": "1 L", "tags": ["cooking", "oil"], "consumable": True},
    {"sku": "CD-110630", "name": "Harvest Table Penne Pasta, 16 oz, 6-pack", "category": "pantry", "uom": "pack",
     "list_price": 8.99, "pack": "6 boxes", "tags": ["pasta", "dinner"], "consumable": True},
    {"sku": "CD-110777", "name": "Spring Peak Sparkling Water, lime, 24 cans", "category": "pantry", "uom": "case",
     "list_price": 11.99, "pack": "24 cans", "tags": ["drinks", "sparkling", "water"], "consumable": True},
    {"sku": "CD-110903", "name": "Trail Mix Snack Packs, 24-count", "category": "pantry", "uom": "box",
     "list_price": 16.49, "pack": "24 packs", "tags": ["snacks", "lunchbox"], "consumable": True},
    {"sku": "CD-111046", "name": "Little Orchard Fruit Pouches, variety, 18-count", "category": "pantry", "uom": "box",
     "list_price": 13.99, "pack": "18 pouches", "tags": ["snacks", "kids", "lunchbox"], "consumable": True},
    # household essentials
    {"sku": "CD-220134", "name": "Everfresh Paper Towels, select-a-size, 12 mega rolls", "category": "household", "uom": "pack",
     "list_price": 24.99, "pack": "12 rolls", "tags": ["paper", "kitchen", "cleaning"], "consumable": True},
    {"sku": "CD-220268", "name": "CloudSoft Bath Tissue, 30 family rolls", "category": "household", "uom": "pack",
     "list_price": 27.99, "pack": "30 rolls", "tags": ["paper", "bathroom"], "consumable": True},
    {"sku": "CD-220391", "name": "ClearTide Laundry Detergent, free & clear, 128 loads", "category": "household", "uom": "jug",
     "list_price": 19.99, "pack": "170 fl oz", "tags": ["laundry", "unscented"], "consumable": True},
    {"sku": "CD-220455", "name": "Lemon Grove Dish Soap, 28 oz, 3-pack", "category": "household", "uom": "pack",
     "list_price": 10.49, "pack": "3 bottles", "tags": ["kitchen", "dishes", "cleaning"], "consumable": True},
    {"sku": "CD-220579", "name": "SparkWash Dishwasher Pods, 78-count", "category": "household", "uom": "tub",
     "list_price": 21.99, "pack": "78 pods", "tags": ["kitchen", "dishes", "dishwasher"], "consumable": True},
    {"sku": "CD-220642", "name": "ToughLine Tall Kitchen Trash Bags, 13 gal, 120-count", "category": "household", "uom": "box",
     "list_price": 18.99, "pack": "120 bags", "tags": ["trash", "kitchen"], "consumable": True},
    {"sku": "CD-220788", "name": "PureWipe Disinfecting Wipes, 80-count, 3-pack", "category": "household", "uom": "pack",
     "list_price": 12.99, "pack": "240 wipes", "tags": ["cleaning", "wipes"], "consumable": True},
    # personal care
    {"sku": "CD-330117", "name": "Brightline Whitening Toothpaste, 6.4 oz, 3-pack", "category": "personal", "uom": "pack",
     "list_price": 11.49, "pack": "3 tubes", "tags": ["dental", "bathroom"], "consumable": True},
    {"sku": "CD-330254", "name": "Meadow & Mint Shampoo, 28 oz", "category": "personal", "uom": "bottle",
     "list_price": 9.99, "pack": "28 fl oz", "tags": ["hair", "shower"], "consumable": True},
    {"sku": "CD-330396", "name": "Sea Cotton Body Wash, 32 oz, 2-pack", "category": "personal", "uom": "pack",
     "list_price": 13.49, "pack": "2 bottles", "tags": ["shower", "soap"], "consumable": True},
    {"sku": "CD-330431", "name": "SolGuard Mineral Sunscreen SPF 50, 6 oz", "category": "personal", "uom": "tube",
     "list_price": 14.99, "pack": "6 oz", "tags": ["sun", "summer", "outdoor"], "consumable": True},
    {"sku": "CD-330570", "name": "Daily Balance Multivitamin Gummies, 150-count", "category": "personal", "uom": "bottle",
     "list_price": 17.99, "pack": "150 gummies", "tags": ["vitamins", "wellness"], "consumable": True},
    # baby
    {"sku": "CD-440129", "name": "Snugglebug Diapers, size 4, 150-count", "category": "baby", "uom": "box",
     "list_price": 44.99, "pack": "150 diapers", "tags": ["diapers", "toddler"], "consumable": True},
    {"sku": "CD-440263", "name": "Snugglebug Sensitive Baby Wipes, 720-count", "category": "baby", "uom": "case",
     "list_price": 19.99, "pack": "9 packs of 80", "tags": ["wipes", "unscented"], "consumable": True},
    {"sku": "CD-440377", "name": "First Steps Toddler Formula, 30 oz", "category": "baby", "uom": "can",
     "list_price": 32.99, "pack": "30 oz", "tags": ["formula", "toddler"], "consumable": True},
    {"sku": "CD-440485", "name": "Dreamnest Convertible Car Seat", "category": "baby", "uom": "each",
     "list_price": 189.99, "pack": "1 seat", "tags": ["car seat", "travel", "safety"], "consumable": False},
    # pets
    {"sku": "CD-550118", "name": "Trailhound Adult Dog Food, chicken & rice, 30 lb", "category": "pets", "uom": "bag",
     "list_price": 46.99, "pack": "30 lb", "tags": ["dog", "food"], "consumable": True},
    {"sku": "CD-550246", "name": "Whiskerwell Indoor Cat Food, salmon, 16 lb", "category": "pets", "uom": "bag",
     "list_price": 31.99, "pack": "16 lb", "tags": ["cat", "food"], "consumable": True},
    {"sku": "CD-550359", "name": "FreshStep Clumping Cat Litter, unscented, 40 lb", "category": "pets", "uom": "box",
     "list_price": 22.99, "pack": "40 lb", "tags": ["cat", "litter", "unscented"], "consumable": True},
    {"sku": "CD-550472", "name": "Trailhound Dental Chews, 36-count", "category": "pets", "uom": "bag",
     "list_price": 24.49, "pack": "36 chews", "tags": ["dog", "treats"], "consumable": True},
    {"sku": "CD-550590", "name": "Orthopedic Pet Bed, large, washable cover", "category": "pets", "uom": "each",
     "list_price": 59.99, "pack": "1 bed", "tags": ["dog", "cat", "bed"], "consumable": False},
    # home & kitchen
    {"sku": "CD-660102", "name": "Hearthside 5.5 qt Stand Mixer, graphite", "category": "kitchen", "uom": "each",
     "list_price": 279.99, "pack": "1 mixer", "tags": ["baking", "appliance", "mixer"], "consumable": False},
    {"sku": "CD-660237", "name": "CrispWave 6 qt Air Fryer", "category": "kitchen", "uom": "each",
     "list_price": 119.99, "pack": "1 air fryer", "tags": ["appliance", "cooking"], "consumable": False},
    {"sku": "CD-660341", "name": "Morning Ridge Single-Serve Coffee Maker", "category": "kitchen", "uom": "each",
     "list_price": 89.99, "pack": "1 brewer", "tags": ["coffee", "appliance", "pods"], "consumable": False},
    {"sku": "CD-660468", "name": "Forge & Field 10-piece Nonstick Cookware Set", "category": "kitchen", "uom": "set",
     "list_price": 149.99, "pack": "10 pieces", "tags": ["cooking", "pans"], "consumable": False},
    {"sku": "CD-660573", "name": "StackRight Glass Food Storage, 18-piece", "category": "kitchen", "uom": "set",
     "list_price": 34.99, "pack": "9 containers + lids", "tags": ["storage", "meal prep", "lunchbox"], "consumable": False},
    {"sku": "CD-660689", "name": "Linen Loft Bath Towels, 6-piece set", "category": "kitchen", "uom": "set",
     "list_price": 39.99, "pack": "6 towels", "tags": ["bath", "home"], "consumable": False},
    # electronics
    {"sku": "CD-770114", "name": "Aria Wireless Earbuds with noise cancelling", "category": "electronics", "uom": "each",
     "list_price": 129.99, "pack": "1 pair", "tags": ["audio", "headphones", "commute"], "consumable": False},
    {"sku": "CD-770229", "name": "Nova X Handheld Game Console", "category": "electronics", "uom": "each",
     "list_price": 349.99, "pack": "1 console", "tags": ["gaming", "console"], "consumable": False, "limit_per_household": 1},
    {"sku": "CD-770336", "name": "Lumen 10 in Tablet, 128 GB", "category": "electronics", "uom": "each",
     "list_price": 219.99, "pack": "1 tablet", "tags": ["tablet", "kids", "streaming"], "consumable": False},
    {"sku": "CD-770447", "name": "PowerLoop 3-in-1 Wireless Charger", "category": "electronics", "uom": "each",
     "list_price": 39.99, "pack": "1 charger", "tags": ["charging", "phone"], "consumable": False},
    {"sku": "CD-770552", "name": "HomeGlow Smart Bulbs, 4-pack", "category": "electronics", "uom": "pack",
     "list_price": 29.99, "pack": "4 bulbs", "tags": ["smart home", "lighting"], "consumable": False},
    # toys & games
    {"sku": "CD-880121", "name": "BrickWorks Creative Building Set, 900 pieces", "category": "toys", "uom": "each",
     "list_price": 49.99, "pack": "900 pieces", "tags": ["building", "kids", "gift"], "consumable": False},
    {"sku": "CD-880243", "name": "Family Game Night Board Game Bundle", "category": "toys", "uom": "set",
     "list_price": 34.99, "pack": "3 games", "tags": ["board games", "family", "gift"], "consumable": False},
    {"sku": "CD-880365", "name": "Washable Art Supplies Mega Kit", "category": "toys", "uom": "each",
     "list_price": 24.99, "pack": "150 pieces", "tags": ["art", "kids", "craft"], "consumable": False},
    # sports & outdoors
    {"sku": "CD-990107", "name": "SummitFlow Insulated Water Bottle, 32 oz", "category": "outdoor", "uom": "each",
     "list_price": 27.99, "pack": "1 bottle", "tags": ["hydration", "gym", "hiking"], "consumable": False},
    {"sku": "CD-990218", "name": "FlexCore Yoga Mat, 6 mm", "category": "outdoor", "uom": "each",
     "list_price": 32.99, "pack": "1 mat", "tags": ["yoga", "fitness", "gym"], "consumable": False},
    {"sku": "CD-990334", "name": "PeakFuel Protein Bars, chocolate, 18-count", "category": "outdoor", "uom": "box",
     "list_price": 26.99, "pack": "18 bars", "tags": ["protein", "snacks", "gym"], "consumable": True},
    {"sku": "CD-990451", "name": "TrailLite 2-Person Backpacking Tent", "category": "outdoor", "uom": "each",
     "list_price": 159.99, "pack": "1 tent", "tags": ["camping", "hiking"], "consumable": False},
]
PRODUCT_BY_SKU = {p["sku"]: p for p in PRODUCTS}

# What each kind of household goes through month to month: sku -> typical
# monthly quantity. The generator derives replenishment from this, with noise.
HOUSEHOLD_TYPES = {
    "young_family": {"name": "Young family", "usage": {
        "CD-440129": 1.2, "CD-440263": 1, "CD-440377": 1.5, "CD-220134": 1, "CD-220268": 1, "CD-220391": 1,
        "CD-111046": 2, "CD-110245": 1, "CD-220788": 1, "CD-220642": 0.5, "CD-110903": 1}},
    "pet_household": {"name": "Pet household", "usage": {
        "CD-550118": 1, "CD-550472": 1, "CD-550359": 1, "CD-550246": 1, "CD-220134": 1, "CD-220642": 0.5,
        "CD-220788": 1, "CD-110245": 1, "CD-220391": 0.5}},
    "busy_professional": {"name": "Busy professional", "usage": {
        "CD-110245": 1.5, "CD-110777": 2, "CD-990334": 1.5, "CD-220579": 0.4, "CD-330254": 0.5, "CD-330396": 0.5,
        "CD-330117": 0.3, "CD-220268": 0.5, "CD-330570": 0.4}},
    "couple": {"name": "Couple", "usage": {
        "CD-110245": 1, "CD-110512": 0.5, "CD-110630": 1, "CD-220134": 0.5, "CD-220268": 0.5, "CD-220455": 0.4,
        "CD-220579": 0.5, "CD-330396": 0.5, "CD-110777": 1, "CD-220391": 0.4}},
    "large_family": {"name": "Large family", "usage": {
        "CD-220134": 2, "CD-220268": 2, "CD-220391": 1.5, "CD-220642": 1, "CD-220579": 1, "CD-110630": 2,
        "CD-110903": 2, "CD-111046": 2, "CD-110388": 1, "CD-330117": 1, "CD-330396": 1, "CD-110777": 2}},
    "empty_nesters": {"name": "Empty nesters", "usage": {
        "CD-110245": 1, "CD-110388": 0.5, "CD-110512": 0.5, "CD-220268": 0.5, "CD-220455": 0.3, "CD-330570": 0.5,
        "CD-330117": 0.3, "CD-220134": 0.5, "CD-550246": 0.5, "CD-550359": 0.5}},
    "student": {"name": "Student", "usage": {
        "CD-110630": 1, "CD-110777": 1, "CD-110903": 1, "CD-220268": 0.3, "CD-220391": 0.3, "CD-330254": 0.3,
        "CD-990334": 1, "CD-110245": 0.5}},
    "fitness_enthusiast": {"name": "Fitness enthusiast", "usage": {
        "CD-990334": 2, "CD-110777": 2, "CD-110388": 1, "CD-330570": 0.5, "CD-330396": 1, "CD-330431": 0.3,
        "CD-220391": 0.5, "CD-110512": 0.5}},
    "home_chef": {"name": "Home chef", "usage": {
        "CD-110512": 1, "CD-110630": 1.5, "CD-220455": 0.5, "CD-220579": 1, "CD-220134": 1, "CD-110245": 1,
        "CD-220642": 0.5, "CD-110388": 0.5}},
}

# --------------------------------------------------------------------------
# Delivery Pass membership tiers (discount off list) and what comes with
# them.
# --------------------------------------------------------------------------
MEMBER_TIERS = [
    {"code": "MEMBER", "name": "Member", "discount_pct": 0, "points_per_usd": 1, "free_delivery_min_usd": 35,
     "blurb": "Free to join: 1 point per dollar and free delivery on orders over $35."},
    {"code": "PLUS", "name": "Plus", "discount_pct": 5, "points_per_usd": 2, "free_delivery_min_usd": 0,
     "blurb": "5% off every item, 2 points per dollar and free delivery on every order, Express included."},
    {"code": "PREMIER", "name": "Premier", "discount_pct": 10, "points_per_usd": 3, "free_delivery_min_usd": 0,
     "blurb": "10% off every item, 3 points per dollar, free Express delivery, priority couriers and early access to limited releases."},
]
TIER_BY_CODE = {t["code"]: t for t in MEMBER_TIERS}

# Multi-buy savings on top of the member discount, by quantity on a line.
MULTI_BUY = [(6, 10), (3, 5)]  # (min qty, extra pct)

DELIVERY_OPTIONS = ["Express delivery", "Same-day delivery", "Scheduled delivery", "Hub pickup"]
EXPRESS_OPTION = "Express delivery"
SCHEDULED_OPTION = "Scheduled delivery"
# Two-hour delivery windows. The model learns which one a household is
# usually home for (`delivery.preferred_window` in the export).
DELIVERY_WINDOWS = ["8-10 am", "10 am-12 pm", "12-2 pm", "3-5 pm", "5-7 pm", "7-9 pm"]
# Couriers are invented, like everything else here.
COURIERS = [("Sam", "e-bike"), ("Priya", "van"), ("Marcus", "cargo bike"), ("Elena", "van"), ("Tariq", "e-bike"),
            ("Jo", "electric van"), ("Lena", "cargo bike"), ("Andre", "van")]
PICKUP_OPTION = "Hub pickup"
DELIVERY_FEE_USD = 5.99
TAX_RATE = 0.0625

# Price match: competitors Couchbase Delivery matches, and the guardrails Customer
# Care applies before approving one.
COMPETITORS = ["Brightway Market", "Northfield Supply", "Oakline Stores"]
PRICE_MATCH_FLOOR_PCT = 70      # a matched price can't go below 70% of list
PRICE_MATCH_MAX_SAVING_USD = 150.0
GOODWILL_MAX_USD = 100.0
RETURN_WINDOW_DAYS = 30
PURCHASE_LIMIT_WINDOW_DAYS = 30

# Fulfillment centers and the states they ship to. Inventory is held per FC.
FULFILLMENT_CENTERS = {
    "FC-NE": {"name": "Northeast Fulfillment Center", "city": "Putnam, CT", "states": ["MA", "NH", "ME", "VT", "CT", "RI"]},
    "FC-NY": {"name": "Hudson Valley Fulfillment Center", "city": "Montgomery, NY", "states": ["NY", "NJ", "PA"]},
    "FC-MA": {"name": "Mid-Atlantic Fulfillment Center", "city": "Hagerstown, MD", "states": ["MD", "VA", "DE", "DC", "WV", "NC"]},
    "FC-SE": {"name": "Southeast Fulfillment Center", "city": "Lakeland, FL", "states": ["FL", "GA", "SC", "AL", "TN"]},
    "FC-SC": {"name": "South Central Fulfillment Center", "city": "Arlington, TX", "states": ["TX", "OK", "LA", "AR", "NM"]},
    "FC-MW": {"name": "Midwest Fulfillment Center", "city": "Terre Haute, IN", "states": ["IL", "IN", "OH", "MI", "WI", "MN", "MO", "KY"]},
    "FC-W": {"name": "West Fulfillment Center", "city": "Ontario, CA", "states": ["CA", "AZ", "NV", "OR", "WA", "CO", "UT"]},
}
STATE_TO_FC = {st: fc for fc, d in FULFILLMENT_CENTERS.items() for st in d["states"]}

REGIONS = {
    "R-BOS-NS": {"name": "Boston North Shore", "state": "MA", "cities": [("Salem", "MA", "01970"), ("Beverly", "MA", "01915"),
                 ("Gloucester", "MA", "01930"), ("Peabody", "MA", "01960"), ("Danvers", "MA", "01923"), ("Lynn", "MA", "01901"),
                 ("Marblehead", "MA", "01945"), ("Newburyport", "MA", "01950"), ("Ipswich", "MA", "01938")]},
    "R-NY-HV": {"name": "Hudson Valley", "state": "NY", "cities": [("Kingston", "NY", "12401"), ("Rhinebeck", "NY", "12572"),
                ("Catskill", "NY", "12414"), ("New Paltz", "NY", "12561"), ("Poughkeepsie", "NY", "12601"), ("Hudson", "NY", "12534"),
                ("Saugerties", "NY", "12477"), ("Woodstock", "NY", "12498")]},
    "R-TX-DFW": {"name": "Dallas-Fort Worth", "state": "TX", "cities": [("Dallas", "TX", "75201"), ("Fort Worth", "TX", "76102"),
                 ("Arlington", "TX", "76010"), ("Plano", "TX", "75074"), ("Irving", "TX", "75060"), ("Denton", "TX", "76201"),
                 ("Garland", "TX", "75040"), ("McKinney", "TX", "75069")]},
    "R-PA-PHL": {"name": "Philadelphia Suburbs", "state": "PA", "cities": [("King of Prussia", "PA", "19406"), ("Media", "PA", "19063"),
                 ("West Chester", "PA", "19380"), ("Doylestown", "PA", "18901"), ("Norristown", "PA", "19401")]},
    "R-FL-TPA": {"name": "Tampa Bay", "state": "FL", "cities": [("Tampa", "FL", "33602"), ("St. Petersburg", "FL", "33701"),
                 ("Clearwater", "FL", "33755"), ("Brandon", "FL", "33511"), ("Lakeland", "FL", "33801")]},
    "R-OH-COL": {"name": "Central Ohio", "state": "OH", "cities": [("Columbus", "OH", "43215"), ("Dublin", "OH", "43017"),
                 ("Westerville", "OH", "43081"), ("Newark", "OH", "43055"), ("Lancaster", "OH", "43130")]},
    "R-CA-SAC": {"name": "Sacramento Valley", "state": "CA", "cities": [("Sacramento", "CA", "95814"), ("Roseville", "CA", "95678"),
                 ("Davis", "CA", "95616"), ("Elk Grove", "CA", "95624"), ("Folsom", "CA", "95630")]},
    "R-NC-RDU": {"name": "Raleigh-Durham", "state": "NC", "cities": [("Raleigh", "NC", "27601"), ("Durham", "NC", "27701"),
                 ("Cary", "NC", "27511"), ("Chapel Hill", "NC", "27514"), ("Apex", "NC", "27502")]},
}

# Where a customer is when the phone has no signal - the reality the app is built for.
CONNECTIVITY_NOTES = ["Subway commute - no signal in the tunnels", "Parking garage under the office - no signal",
                      "High-rise lobby and elevator - no signal on the way up", "Rural drive home - dead zone on the county road",
                      "Flies weekly - shops in airplane mode", "Basement apartment - spotty Wi-Fi",
                      "Good signal", "Good signal", "Good signal"]

HUB_HOURS = ["Daily 7am-10pm", "Mon-Sat 8am-10pm, Sun 9am-8pm", "Daily 8am-9pm", "Daily 6am-11pm"]
HUB_SERVICES = ["Express delivery", "Pickup counter", "Returns drop-off", "Pickup lockers", "Chilled storage", "E-bike couriers"]
BAY_BY_CATEGORY = {"pantry": "A", "household": "B", "personal": "C", "baby": "D", "pets": "E", "kitchen": "F",
                     "electronics": "G", "toys": "H", "outdoor": "J"}


def _h(*parts) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _hubs() -> dict:
    """One delivery hub per city in every region. Deterministic, so the generator,
    the loader and the tests agree on ids without a store table in the export."""
    out = {}
    for ri, (rid, reg) in enumerate(REGIONS.items(), start=1):
        for ci, (city, state, zipc) in enumerate(reg["cities"], start=1):
            sid = f"HB-{ri:02d}{ci:02d}"
            h = _h("store", sid)
            out[sid] = {"hub_id": sid, "name": f"{city} Hub", "city": city, "state": state, "zip": zipc,
                        "street": f"{100 + h % 1800} {['Market St', 'Commerce Way', 'Main St', 'Depot Row', 'Plaza Dr'][h % 5]}",
                        "region_id": rid, "region_name": reg["name"], "hours": HUB_HOURS[h % len(HUB_HOURS)],
                        "phone": f"({200 + h % 700}) 555-{1000 + h % 9000:04d}"[:14],
                        "services": [s for i, s in enumerate(HUB_SERVICES) if i < 3 or (h >> i) & 1],
                        "fulfillment_center": STATE_TO_FC.get(state, "FC-MW")}
    return out


HUBS = _hubs()


def member_price(sku: str, tier_code: str, qty: int = 1) -> float:
    """Unit price for a customer: list, less the member tier discount, less
    any multi-buy saving for the line quantity."""
    p = PRODUCT_BY_SKU[sku]
    pct = TIER_BY_CODE[tier_code]["discount_pct"]
    for min_qty, extra in MULTI_BUY:
        if qty >= min_qty:
            pct += extra
            break
    return round(p["list_price"] * (1 - pct / 100.0), 2)


def initial_inventory(fc: str) -> dict:
    """Deterministic on-hand units per SKU at a fulfillment center. A few
    SKUs are deliberately short so partial shipments and backorders show up."""
    out = {}
    for p in PRODUCTS:
        base = 60 if p["consumable"] else 14
        out[p["sku"]] = base + _h(fc, p["sku"]) % (base * 4)
    # Hero shortages: the handheld console is tight everywhere, coffee pods are
    # nearly gone in the Northeast, dog food is out in the Hudson Valley.
    out["CD-770229"] = 2 + _h(fc, "short") % 3
    if fc == "FC-NE":
        out["CD-110245"] = 1
    if fc == "FC-NY":
        out["CD-550118"] = 0
    return out


def fc_for_state(state: str) -> str:
    return STATE_TO_FC.get(state, "FC-MW")


def bay_for(hub_id: str, sku: str) -> str:
    p = PRODUCT_BY_SKU[sku]
    return f"{BAY_BY_CATEGORY[p['category']]}{1 + _h(hub_id, sku) % 14}"


def hub_doc_body(hub_id: str) -> dict:
    """What the phone holds about the customer's home hub: hours, services,
    how long Express takes from it and the pickup bay of every product, so
    delivery estimates and pickup lookups work with no signal."""
    s = HUBS[hub_id]
    return {**s, "bays": {p["sku"]: bay_for(hub_id, p["sku"]) for p in PRODUCTS},
            "pickup_ready_minutes": 90 + _h(hub_id, "pickup") % 60,
            "express_eta_minutes": express_minutes(hub_id), "couriers_on_shift": 4 + _h(hub_id, "couriers") % 9}


def express_minutes(hub_id: str | None) -> int:
    """Typical door-to-door time for an Express order from a hub."""
    return 25 + _h(hub_id or "-", "express") % 30


def preferred_window(customer_id: str) -> str:
    """The delivery window the model predicts for a household. Derived from
    the id so the generator needs no extra random draw."""
    return DELIVERY_WINDOWS[_h("window", customer_id) % len(DELIVERY_WINDOWS)]


def courier_for(hub_id: str | None, seed: str) -> dict:
    name, vehicle = COURIERS[_h("courier", hub_id or "-", seed) % len(COURIERS)]
    return {"name": name, "vehicle": vehicle}


def public_catalog() -> dict:
    """What the mobile app syncs as the `catalog` document."""
    return {
        "categories": {k: v["name"] for k, v in CATEGORIES.items()},
        "category_icons": {k: v["icon"] for k, v in CATEGORIES.items()},
        "products": PRODUCTS,
        "member_tiers": MEMBER_TIERS,
        "multi_buy": [{"min_qty": q, "extra_pct": e} for q, e in MULTI_BUY],
        "delivery_options": DELIVERY_OPTIONS,
        "pickup_option": PICKUP_OPTION,
        "express_option": EXPRESS_OPTION,
        "scheduled_option": SCHEDULED_OPTION,
        "delivery_windows": DELIVERY_WINDOWS,
        "delivery_fee_usd": DELIVERY_FEE_USD,
        "tax_rate": TAX_RATE,
        "competitors": COMPETITORS,
        "price_match_floor_pct": PRICE_MATCH_FLOOR_PCT,
        "fulfillment_centers": {k: {"name": v["name"], "city": v["city"]} for k, v in FULFILLMENT_CENTERS.items()},
        "household_types": {k: v["name"] for k, v in HOUSEHOLD_TYPES.items()},
    }
