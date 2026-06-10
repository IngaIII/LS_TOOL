import os
from datetime import date
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")

def seed_database(db):
    from models import User, Product, PriceTier, Account

    # Admin user — password set via ADMIN_PASSWORD env var, never hardcoded
    if not db.query(User).first():
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            raise RuntimeError(
                "ADMIN_PASSWORD environment variable is not set. "
                "Set it in Railway Variables (or a .env file locally) before starting."
            )
        admin = User(
            username="admin",
            password_hash=pwd_context.hash(password),
            full_name="Administrator",
            role="admin"
        )
        db.add(admin)
        db.commit()

    # Products
    if not db.query(Product).first():
        products = [
            Product(name="Stock Brick", category="brick", unit="item"),
            Product(name="M6 Block", category="block", unit="item"),
            Product(name="M9 Block", category="block", unit="item"),
            Product(name="Building Sand", category="building", unit="ton"),
            Product(name="Sabunge", category="sabunge", unit="ton"),
            Product(name="Plaster Sand", category="plaster", unit="ton"),
            Product(name="River Sand", category="river_sand", unit="ton"),
            Product(name="C/Stone", category="stone", unit="ton"),
            Product(name="M/P Cement", category="cement", unit="item"),
            Product(name="Afrisam Cement", category="cement", unit="item"),
            Product(name="TLB Hire", category="tlb", unit="hour"),
            Product(name="Water", category="water", unit="litre"),
            Product(name="Diesel Security", category="diesel", unit="item"),
        ]
        db.add_all(products)
        db.commit()

        today = date.today()
        brick = db.query(Product).filter_by(name="Stock Brick").first()
        m6 = db.query(Product).filter_by(name="M6 Block").first()
        m9 = db.query(Product).filter_by(name="M9 Block").first()
        building = db.query(Product).filter_by(name="Building Sand").first()
        sabunge = db.query(Product).filter_by(name="Sabunge").first()
        plaster = db.query(Product).filter_by(name="Plaster Sand").first()
        river = db.query(Product).filter_by(name="River Sand").first()
        stone = db.query(Product).filter_by(name="C/Stone").first()
        mp_cement = db.query(Product).filter_by(name="M/P Cement").first()
        af_cement = db.query(Product).filter_by(name="Afrisam Cement").first()
        tlb = db.query(Product).filter_by(name="TLB Hire").first()
        water = db.query(Product).filter_by(name="Water").first()
        diesel = db.query(Product).filter_by(name="Diesel Security").first()

        tiers = [
            PriceTier(product_id=brick.id, tier_label="Each", quantity=1, price_zar=8, effective_from=today),
            PriceTier(product_id=m6.id, tier_label="Each", quantity=1, price_zar=11, effective_from=today),
            PriceTier(product_id=m9.id, tier_label="Each", quantity=1, price_zar=15, effective_from=today),
            PriceTier(product_id=building.id, tier_label="W/Barrow", quantity=0.1, price_zar=50, effective_from=today),
            PriceTier(product_id=building.id, tier_label="1 Ton", quantity=1, price_zar=500, effective_from=today),
            PriceTier(product_id=building.id, tier_label="4 Ton", quantity=4, price_zar=2000, effective_from=today),
            PriceTier(product_id=building.id, tier_label="8 Ton", quantity=8, price_zar=3000, effective_from=today),
            PriceTier(product_id=building.id, tier_label="10 Ton", quantity=10, price_zar=3500, effective_from=today),
            PriceTier(product_id=building.id, tier_label="20 Ton", quantity=20, price_zar=4500, effective_from=today),
            PriceTier(product_id=sabunge.id, tier_label="W/Barrow", quantity=0.1, price_zar=50, effective_from=today),
            PriceTier(product_id=sabunge.id, tier_label="1 Ton", quantity=1, price_zar=500, effective_from=today),
            PriceTier(product_id=sabunge.id, tier_label="4 Ton", quantity=4, price_zar=2000, effective_from=today),
            PriceTier(product_id=sabunge.id, tier_label="8 Ton", quantity=8, price_zar=3000, effective_from=today),
            PriceTier(product_id=sabunge.id, tier_label="10 Ton", quantity=10, price_zar=3500, effective_from=today),
            PriceTier(product_id=sabunge.id, tier_label="20 Ton", quantity=20, price_zar=4500, effective_from=today),
            PriceTier(product_id=plaster.id, tier_label="W/Barrow", quantity=0.1, price_zar=80, effective_from=today),
            PriceTier(product_id=plaster.id, tier_label="1 Ton", quantity=1, price_zar=800, effective_from=today),
            PriceTier(product_id=plaster.id, tier_label="4 Ton", quantity=4, price_zar=2500, effective_from=today),
            PriceTier(product_id=plaster.id, tier_label="8 Ton", quantity=8, price_zar=3500, effective_from=today),
            PriceTier(product_id=plaster.id, tier_label="10 Ton", quantity=10, price_zar=3800, effective_from=today),
            PriceTier(product_id=plaster.id, tier_label="20 Ton", quantity=20, price_zar=6000, effective_from=today),
            PriceTier(product_id=river.id, tier_label="W/Barrow", quantity=0.1, price_zar=80, effective_from=today),
            PriceTier(product_id=river.id, tier_label="1 Ton", quantity=1, price_zar=800, effective_from=today),
            PriceTier(product_id=river.id, tier_label="4 Ton", quantity=4, price_zar=2800, effective_from=today),
            PriceTier(product_id=river.id, tier_label="8 Ton", quantity=8, price_zar=3800, effective_from=today),
            PriceTier(product_id=river.id, tier_label="10 Ton", quantity=10, price_zar=4000, effective_from=today),
            PriceTier(product_id=river.id, tier_label="20 Ton", quantity=20, price_zar=6500, effective_from=today),
            PriceTier(product_id=stone.id, tier_label="W/Barrow", quantity=0.1, price_zar=80, effective_from=today),
            PriceTier(product_id=stone.id, tier_label="1 Ton", quantity=1, price_zar=800, effective_from=today),
            PriceTier(product_id=stone.id, tier_label="4 Ton", quantity=4, price_zar=3000, effective_from=today),
            PriceTier(product_id=stone.id, tier_label="8 Ton", quantity=8, price_zar=4000, effective_from=today),
            PriceTier(product_id=stone.id, tier_label="20 Ton", quantity=20, price_zar=6500, effective_from=today),
            PriceTier(product_id=mp_cement.id, tier_label="Each", quantity=1, price_zar=160, effective_from=today),
            PriceTier(product_id=af_cement.id, tier_label="Each", quantity=1, price_zar=170, effective_from=today),
            PriceTier(product_id=tlb.id, tier_label="Per Hour (min 3)", quantity=1, price_zar=1000, effective_from=today),
            PriceTier(product_id=tlb.id, tier_label="Per Day (8-5)", quantity=9, price_zar=7500, effective_from=today),
            PriceTier(product_id=water.id, tier_label="5000L", quantity=5000, price_zar=2000, effective_from=today),
            PriceTier(product_id=water.id, tier_label="10000L", quantity=10000, price_zar=3500, effective_from=today),
            PriceTier(product_id=diesel.id, tier_label="Fixed", quantity=1, price_zar=3000, effective_from=today),
        ]
        db.add_all(tiers)
        db.commit()

    # Chart of accounts
    if not db.query(Account).first():
        accounts = [
            Account(code="1000", name="Cash on Hand", account_type="asset", normal_balance="debit"),
            Account(code="1010", name="Bank Account", account_type="asset", normal_balance="debit"),
            Account(code="1100", name="Accounts Receivable", account_type="asset", normal_balance="debit"),
            Account(code="1200", name="Inventory - Bricks & Blocks", account_type="asset", normal_balance="debit"),
            Account(code="1210", name="Inventory - Sand & Stone", account_type="asset", normal_balance="debit"),
            Account(code="1220", name="Inventory - Cement", account_type="asset", normal_balance="debit"),
            Account(code="1230", name="Inventory - Water", account_type="asset", normal_balance="debit"),
            Account(code="2000", name="Accounts Payable", account_type="liability", normal_balance="credit"),
            Account(code="2100", name="Customer Deposits", account_type="liability", normal_balance="credit"),
            Account(code="3000", name="Owner's Equity", account_type="equity", normal_balance="credit"),
            Account(code="3100", name="Retained Earnings", account_type="equity", normal_balance="credit"),
            Account(code="4000", name="Sales - Bricks & Blocks", account_type="revenue", normal_balance="credit"),
            Account(code="4010", name="Sales - Building Sand", account_type="revenue", normal_balance="credit"),
            Account(code="4020", name="Sales - Sabunge", account_type="revenue", normal_balance="credit"),
            Account(code="4030", name="Sales - Plaster Sand", account_type="revenue", normal_balance="credit"),
            Account(code="4040", name="Sales - River Sand", account_type="revenue", normal_balance="credit"),
            Account(code="4050", name="Sales - C/Stone", account_type="revenue", normal_balance="credit"),
            Account(code="4060", name="Sales - Cement", account_type="revenue", normal_balance="credit"),
            Account(code="4070", name="TLB Hire Revenue", account_type="revenue", normal_balance="credit"),
            Account(code="4080", name="Diesel Security Income", account_type="revenue", normal_balance="credit"),
            Account(code="4090", name="Water Delivery Revenue", account_type="revenue", normal_balance="credit"),
            Account(code="4095", name="Transport & Delivery Revenue", account_type="revenue", normal_balance="credit"),
            Account(code="5000", name="Cost of Goods Sold", account_type="expense", normal_balance="debit"),
            Account(code="5100", name="Vehicle Operating Costs", account_type="expense", normal_balance="debit"),
            Account(code="5200", name="TLB Operating Costs", account_type="expense", normal_balance="debit"),
            Account(code="5300", name="Labour", account_type="expense", normal_balance="debit"),
            Account(code="5400", name="General & Administrative", account_type="expense", normal_balance="debit"),
        ]
        db.add_all(accounts)
        db.commit()
        print("Database seeded successfully.")
