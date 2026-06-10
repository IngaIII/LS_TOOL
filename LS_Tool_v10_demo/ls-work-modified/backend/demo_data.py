"""
Demo / test data seeder
=======================
Populates the system with realistic sample data by calling the real API,
so all pricing, allocation, and general-ledger logic runs exactly as in
normal use (the trial balance will balance).

Usage:
    python demo_data.py --url http://localhost:8000 --password YOUR_ADMIN_PASSWORD
    python demo_data.py --url https://your-app.up.railway.app --password YOUR_ADMIN_PASSWORD

Safety: refuses to run if the system already has orders, unless --force is given.
There is no bulk-delete, so only run this against a fresh/demo instance,
never against a live database with real records.
"""
import argparse, random, sys
from datetime import date, timedelta

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

random.seed(7)  # same demo data every run

TODAY = date.today()
def d(days_ago): return str(TODAY - timedelta(days=days_ago))

# ── Demo cast ────────────────────────────────────────────────────────────────
INDIVIDUALS = [
    ("Sipho Ndlovu",      "073 482 1190", "12 Mimosa St, Kariega"),
    ("Maria van Wyk",     "082 334 7765", "8 Protea Ave, Despatch"),
    ("Johan Botha",       "071 905 2231", "Plot 14, Greenbushes"),
    ("Thandi Mahlangu",   "060 118 4472", "33 Lily Cres, KwaNobuhle"),
    ("Pieter Steyn",      "083 667 0918", "5 Akkerboom Rd, Uitenhage"),
    ("Nomvula Dlamini",   "079 552 8804", "21 Daisy St, Motherwell"),
    ("Craig Williams",    "084 220 6677", "17 Harbour View, Bluewater Bay"),
    ("Zanele Mokoena",    "061 774 3309", "2 Begonia Cl, KwaDwesi"),
]
STORES = [  # (name, payment behaviour)
    ("Build It Kariega",        "good"),     # pays the account regularly
    ("Cashbuild Uitenhage",     "slow"),     # pays late, partial
    ("PE Hardware & Timber",    "overdue"),  # 60+ days outstanding
]

class Api:
    def __init__(self, base, password):
        self.base = base.rstrip("/") + "/api/v1"
        r = requests.post(self.base + "/auth/login",
                          data={"username": "admin", "password": password})
        if not r.ok:
            sys.exit(f"Login failed ({r.status_code}): {r.text}")
        self.h = {"Authorization": "Bearer " + r.json()["access_token"]}
    def get(self, p, **kw):  return self._chk(requests.get(self.base + p, headers=self.h, **kw))
    def post(self, p, json): return self._chk(requests.post(self.base + p, headers=self.h, json=json))
    def put(self, p, json):  return self._chk(requests.put(self.base + p, headers=self.h, json=json))
    @staticmethod
    def _chk(r):
        if not r.ok:
            raise RuntimeError(f"{r.request.method} {r.url} -> {r.status_code}: {r.text[:200]}")
        return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--password", required=True, help="admin password")
    ap.add_argument("--force", action="store_true", help="seed even if orders already exist")
    args = ap.parse_args()

    api = Api(args.url, args.password)

    if api.get("/orders") and not args.force:
        sys.exit("This system already has orders. Use --force only on a demo instance.")

    # ── Products: use the seeded catalogue, top up if thin ───────────────────
    products = api.get("/products")
    tiers = [(p, t) for p in products for t in p["tiers"]]
    if not tiers:
        for name, cat, unit, price in [("River Sand", "sand", "ton", 450.0),
                                       ("Building Sand", "sand", "ton", 420.0),
                                       ("19mm Stone", "stone", "ton", 520.0),
                                       ("Cement 50kg", "cement", "bag", 105.0)]:
            p = api.post("/products", {"name": name, "category": cat, "unit": unit})
            api.post(f"/products/{p['id']}/prices",
                     {"tier_label": "1 " + unit.title(), "quantity": 1, "price_zar": price})
        products = api.get("/products")
        tiers = [(p, t) for p in products for t in p["tiers"]]
    print(f"Using {len(products)} products / {len(tiers)} price tiers")

    # ── Customers & stores ────────────────────────────────────────────────────
    existing = {c["name"].lower(): c["id"] for c in api.get("/customers")}
    def customer(name, phone=None, address=None, ctype="individual"):
        if name.lower() in existing: return existing[name.lower()]
        c = api.post("/customers", {"name": name, "phone": phone, "address": address,
                                    "customer_type": ctype})
        existing[name.lower()] = c["id"]; return c["id"]

    people = [customer(n, p, a) for n, p, a in INDIVIDUALS]
    stores = {name: (customer(name, ctype="hardware_store"), beh) for name, beh in STORES}
    print(f"{len(people)} individual customers, {len(stores)} hardware stores")

    # ── Order helper ──────────────────────────────────────────────────────────
    drivers = [("Lucky M.", "CJ 44 821"), ("Andre P.", "CJ 90 113"), ("Bongani S.", "CJ 12 558")]
    def make_order(cust_id, days_ago, n_items=None, transport=None, confirm=True,
                   deliver_to_store=None, delivered=True):
        body = {"customer_id": cust_id, "order_date": d(days_ago)}
        if transport: body["transport_price"] = transport
        o = api.post("/orders", body)
        for p, t in random.sample(tiers, n_items or random.randint(1, 3)):
            api.post(f"/orders/{o['id']}/items",
                     {"product_id": p["id"], "price_tier_id": t["id"],
                      "quantity": random.randint(1, 6)})
        if confirm:
            api.put(f"/orders/{o['id']}/status", {"status": "confirmed"})
        drv, reg = random.choice(drivers)
        dl = {"order_id": o["id"], "scheduled_date": d(max(days_ago - 1, 0)),
              "driver_name": drv, "vehicle_reg": reg}
        if deliver_to_store:
            dl.update({"delivery_type": "hardware", "hardware_store_customer_id": deliver_to_store})
        dlv = api.post("/deliveries", dl)
        if delivered and confirm:
            api.put(f"/deliveries/{dlv['id']}", {"status": "completed", "actual_date": d(max(days_ago - 1, 0))})
            api.put(f"/orders/{o['id']}/status", {"status": "delivered"})
        return api.get(f"/orders/{o['id']}")

    # ── Individual customers: ~75% fully paid, some partial, some unpaid ─────
    n_orders = 0
    for cid in people:
        for _ in range(random.randint(2, 4)):
            o = make_order(cid, random.randint(3, 110),
                           transport=random.choice([None, None, 350, 500, 750]))
            n_orders += 1
            roll = random.random()
            if roll < 0.75:   amt = o["total_zar"]                       # paid in full
            elif roll < 0.9:  amt = round(o["total_zar"] * random.choice([0.5, 0.6]), 2)  # deposit
            else:             amt = 0                                    # still owing
            if amt > 0:
                api.post("/payments", {"order_id": o["id"], "amount_zar": amt,
                                       "payment_date": d(random.randint(0, 2)),
                                       "method": random.choice(["cash", "eft", "eft"]),
                                       "reference": f"INV-{o['id']:04d}"})
    print(f"{n_orders} individual orders created")

    # ── Hardware stores: orders delivered to the store, account payments ─────
    for name, (sid, behaviour) in stores.items():
        totals = 0
        for _ in range(random.randint(4, 6)):
            buyer = random.choice(people)
            age = {"good": random.randint(5, 45),
                   "slow": random.randint(20, 75),
                   "overdue": random.randint(45, 100)}[behaviour]
            o = make_order(buyer, age, transport=random.choice([None, 350, 500]),
                           deliver_to_store=sid)
            totals += o["total_zar"]
        # account payment behaviour (oldest-first allocation through the real endpoint)
        pay_ratio = {"good": 0.85, "slow": 0.45, "overdue": 0.15}[behaviour]
        amount = round(totals * pay_ratio, 2)
        if amount > 0:
            api.post("/payments", {"customer_id": sid, "amount_zar": amount,
                                   "payment_date": d(random.randint(1, 10)),
                                   "method": "eft", "reference": "STATEMENT-MAY"})
        print(f"  {name}: invoiced ~R{totals:,.0f}, paid R{amount:,.0f} on account ({behaviour})")

    # ── A couple of open quotes (pipeline) ────────────────────────────────────
    for _ in range(3):
        o = api.post("/orders", {"customer_id": random.choice(people), "order_date": d(random.randint(0, 4))})
        for p, t in random.sample(tiers, 2):
            api.post(f"/orders/{o['id']}/items", {"product_id": p["id"], "price_tier_id": t["id"], "quantity": random.randint(1, 4)})
    print("3 open quotes")

    # ── TLB bookings ──────────────────────────────────────────────────────────
    for i in range(5):
        body = {"customer_id": random.choice(people), "booking_date": d(random.randint(2, 60)),
                "rate_type": random.choice(["hourly", "hourly", "daily"]),
                "hours_billed": random.randint(3, 8),
                "diesel_included": random.random() < 0.4,
                "transport_price": random.choice([0, 0, 800])}
        t = api.post("/tlb", body)
        if random.random() < 0.6:
            full = api.get(f"/tlb/{t['id']}")
            api.post("/payments", {"tlb_booking_id": t["id"], "amount_zar": full["total_zar"],
                                   "payment_date": d(random.randint(0, 5)), "method": "eft"})
    print("5 TLB bookings (some paid)")

    # ── One lay-buy ───────────────────────────────────────────────────────────
    o = make_order(random.choice(people), 35, n_items=3, delivered=False)
    lb = api.post("/laybuys", {"order_id": o["id"], "months": 4, "start_date": d(35)})
    inst = api.get("/laybuys")[-1]["installments"]
    api.put(f"/laybuys/{api.get('/laybuys')[-1]['id']}/installments/{inst[0]['id']}/pay", {})
    print("1 lay-buy with first installment paid")

    # ── Summary ───────────────────────────────────────────────────────────────
    tb = api.get("/gl/trial-balance")
    td, tc = sum(r["total_debit"] for r in tb), sum(r["total_credit"] for r in tb)
    print("\n── Done ──")
    print(f"Orders: {len(api.get('/orders'))} | Payments: {len(api.get('/payments'))} | "
          f"Deliveries: {len(api.get('/deliveries'))}")
    for s in api.get("/stores"):
        print(f"  {s['name']}: owes R{s['balance']:,.2f} "
              f"(oldest unpaid {s['oldest_unpaid_days']}d)")
    print(f"Trial balance: debits R{td:,.2f} / credits R{tc:,.2f} "
          f"{'BALANCED ✓' if abs(td-tc) < 0.01 else 'UNBALANCED ✗'}")

if __name__ == "__main__":
    main()
