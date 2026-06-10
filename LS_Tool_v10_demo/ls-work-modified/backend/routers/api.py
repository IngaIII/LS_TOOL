from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta
from typing import Optional
from pydantic import BaseModel
import calendar
from database import get_db
from auth import verify_password, create_token, get_current_user, require_admin, hash_password
from models import User, Customer, Product, PriceTier, Order, OrderItem, Delivery, TLBBooking, Payment, Account, JournalEntry, Laybuy, LaybuyInstallment
import gl.service as gl

def add_months(d: date, months: int) -> date:
    """Add months to a date, clamping to month-end if needed."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

router = APIRouter()

# ── Auth ──────────────────────────────────────────────────────────────────────
@router.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=form.username, is_active=True).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer", "role": user.role, "full_name": user.full_name}

@router.get("/auth/me")
def me(current_user=Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username,
            "full_name": current_user.full_name, "role": current_user.role}

# ── Customers ─────────────────────────────────────────────────────────────────
class CustomerIn(BaseModel):
    name: str; phone: Optional[str]=None; email: Optional[str]=None
    address: Optional[str]=None; notes: Optional[str]=None
    customer_type: str = "individual"

def _check_customer_type(t):
    if t not in ("individual", "hardware_store"):
        raise HTTPException(400, "customer_type must be 'individual' or 'hardware_store'")

@router.get("/customers")
def list_customers(search: Optional[str]=None, db: Session=Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Customer)
    if search:
        q = q.filter(Customer.name.ilike(f"%{search}%"))
    return [{"id":c.id,"name":c.name,"phone":c.phone,"email":c.email,"address":c.address,
             "customer_type":c.customer_type or "individual"} for c in q.order_by(Customer.name).all()]

@router.post("/customers")
def create_customer(data: CustomerIn, db: Session=Depends(get_db), _=Depends(get_current_user)):
    _check_customer_type(data.customer_type)
    # Duplicate name check (case-insensitive)
    existing = db.query(Customer).filter(func.lower(Customer.name)==data.name.strip().lower()).first()
    if existing:
        raise HTTPException(400, f"A customer named '{existing.name}' already exists (ID {existing.id}). Edit that record instead.")
    c = Customer(**data.dict())
    db.add(c); db.commit(); db.refresh(c)
    return {"id":c.id,"name":c.name}

@router.get("/customers/{cid}")
def get_customer(cid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Customer).get(cid)
    if not c: raise HTTPException(404)
    orders = [{"id":o.id,"order_number":o.order_number,"status":o.status,"total_zar":o.total_zar,"order_date":str(o.order_date)} for o in c.orders]
    return {"id":c.id,"name":c.name,"phone":c.phone,"email":c.email,"address":c.address,"notes":c.notes,
            "customer_type":c.customer_type or "individual","orders":orders}

@router.put("/customers/{cid}")
def update_customer(cid: int, data: CustomerIn, db: Session=Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Customer).get(cid)
    if not c: raise HTTPException(404)
    _check_customer_type(data.customer_type)
    for k,v in data.dict().items(): setattr(c,k,v)
    db.commit()
    return {"id":c.id,"name":c.name}

# ── Products & Pricing ────────────────────────────────────────────────────────
@router.get("/products")
def list_products(include_inactive: bool=False, db: Session=Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Product)
    if not include_inactive:
        q = q.filter_by(is_active=True)
    products = q.order_by(Product.name).all()
    result = []
    for p in products:
        tiers = db.query(PriceTier).filter_by(product_id=p.id, effective_to=None).order_by(PriceTier.quantity).all()
        result.append({
            "id":p.id,"name":p.name,"category":p.category,"unit":p.unit,
            "description":p.description,"is_active":p.is_active,
            "tiers":[{"id":t.id,"tier_label":t.tier_label,"quantity":t.quantity,"price_zar":t.price_zar,
                      "effective_from":str(t.effective_from)} for t in tiers]
        })
    return result

class ProductIn(BaseModel):
    name: str; category: str; unit: str
    description: Optional[str]=None

@router.post("/products")
def create_product(data: ProductIn, db: Session=Depends(get_db), _=Depends(require_admin)):
    name = data.name.strip()
    if not name or not data.category.strip() or not data.unit.strip():
        raise HTTPException(400, "Name, category and unit are required")
    existing = db.query(Product).filter(func.lower(Product.name)==name.lower()).first()
    if existing:
        if existing.is_active:
            raise HTTPException(400, f"A product named '{existing.name}' already exists.")
        raise HTTPException(400, f"An inactive product named '{existing.name}' exists. Reactivate it instead.")
    p = Product(name=name, category=data.category.strip().lower(), unit=data.unit.strip(), description=data.description)
    db.add(p); db.commit(); db.refresh(p)
    return {"id":p.id,"name":p.name,"category":p.category,"unit":p.unit}

class ProductUpdate(BaseModel):
    name: Optional[str]=None; category: Optional[str]=None; unit: Optional[str]=None
    description: Optional[str]=None; is_active: Optional[bool]=None

@router.put("/products/{pid}")
def update_product(pid: int, data: ProductUpdate, db: Session=Depends(get_db), _=Depends(require_admin)):
    p = db.query(Product).get(pid)
    if not p: raise HTTPException(404, "Product not found")
    if data.name is not None:
        name = data.name.strip()
        if not name: raise HTTPException(400, "Name cannot be empty")
        dup = db.query(Product).filter(func.lower(Product.name)==name.lower(), Product.id!=pid).first()
        if dup: raise HTTPException(400, f"Another product named '{dup.name}' already exists.")
        p.name = name
    if data.category is not None and data.category.strip(): p.category = data.category.strip().lower()
    if data.unit is not None and data.unit.strip(): p.unit = data.unit.strip()
    if data.description is not None: p.description = data.description
    if data.is_active is not None: p.is_active = data.is_active
    db.commit()
    return {"id":p.id,"name":p.name,"category":p.category,"unit":p.unit,"is_active":p.is_active}

@router.get("/pricelist")
def price_list(db: Session=Depends(get_db), _=Depends(get_current_user)):
    tiers = db.query(PriceTier).filter_by(effective_to=None).join(Product).filter(Product.is_active==True).order_by(Product.name).all()
    return [{"product":t.product.name,"category":t.product.category,"tier":t.tier_label,"price_zar":t.price_zar} for t in tiers]

class PriceTierIn(BaseModel):
    tier_label: str; quantity: float; price_zar: float

@router.post("/products/{pid}/prices")
def add_price(pid: int, data: PriceTierIn, db: Session=Depends(get_db), _=Depends(require_admin)):
    p = db.query(Product).get(pid)
    if not p: raise HTTPException(404, "Product not found")
    if not data.tier_label.strip():
        raise HTTPException(400, "Tier label is required")
    if data.price_zar < 0 or data.quantity <= 0:
        raise HTTPException(400, "Quantity must be positive and price cannot be negative")
    # Expire old tier with same label (price history is preserved)
    old = db.query(PriceTier).filter_by(product_id=pid, tier_label=data.tier_label.strip(), effective_to=None).first()
    if old: old.effective_to = date.today()
    t = PriceTier(product_id=pid, tier_label=data.tier_label.strip(), quantity=data.quantity,
                  price_zar=data.price_zar, effective_from=date.today())
    db.add(t); db.commit(); db.refresh(t)
    return {"id":t.id,"tier_label":t.tier_label,"price_zar":t.price_zar}

@router.delete("/products/{pid}/prices/{tid}")
def retire_price(pid: int, tid: int, db: Session=Depends(get_db), _=Depends(require_admin)):
    """Retire a price tier (sets effective_to). Past orders keep their reference; it just stops being offered."""
    t = db.query(PriceTier).filter_by(id=tid, product_id=pid, effective_to=None).first()
    if not t: raise HTTPException(404, "Active price tier not found")
    t.effective_to = date.today()
    db.commit()
    return {"id":t.id,"retired":True}

# ── Orders ────────────────────────────────────────────────────────────────────
class OrderIn(BaseModel):
    customer_id: int; order_date: str; delivery_address: Optional[str]=None; notes: Optional[str]=None
    discount_amount: Optional[float]=0.0        # flat rand discount
    discount_pct: Optional[float]=0.0           # percentage discount (0-100)
    discount_reason: Optional[str]=None
    transport_price: Optional[float]=0.0        # transport / delivery charge
    transport_notes: Optional[str]=None

class OrderItemIn(BaseModel):
    product_id: int; price_tier_id: int; quantity: int
    custom_unit_price: Optional[float]=None     # override tier price (None = use tier)
    custom_price_reason: Optional[str]=None

def recalculate_order_total(o) -> float:
    """Compute order total: sum of line items + transport - discounts."""
    items_subtotal = sum(i.line_total_zar for i in o.items)
    transport = o.transport_price or 0.0
    subtotal = items_subtotal + transport
    # Apply percentage discount first, then flat discount
    if o.discount_pct and o.discount_pct > 0:
        subtotal = subtotal * (1 - o.discount_pct / 100)
    if o.discount_amount and o.discount_amount > 0:
        subtotal = subtotal - o.discount_amount
    return max(subtotal, 0.0)

def order_dict(o):
    paid = sum(p.amount_zar for p in o.payments)
    items_subtotal = sum(i.line_total_zar for i in o.items)
    return {
        "id":o.id,"order_number":o.order_number,"customer_id":o.customer_id,
        "customer_name":o.customer.name,"order_date":str(o.order_date),
        "status":o.status,"total_zar":o.total_zar,"paid":paid,"balance":o.total_zar-paid,
        "delivery_address":o.delivery_address,"notes":o.notes,
        # Custom pricing summary
        "items_subtotal": items_subtotal,
        "transport_price": o.transport_price or 0.0,
        "transport_notes": o.transport_notes,
        "discount_amount": o.discount_amount or 0.0,
        "discount_pct": o.discount_pct or 0.0,
        "discount_reason": o.discount_reason,
        "items":[{
            "id":i.id,"product_name":i.product.name,"tier_label":i.price_tier.tier_label,
            "quantity":i.quantity,"unit_price_zar":i.unit_price_zar,"line_total_zar":i.line_total_zar,
            "custom_unit_price":i.custom_unit_price,"custom_price_reason":i.custom_price_reason,
            "is_custom_price": i.custom_unit_price is not None,
            "tier_price_zar": i.price_tier.price_zar,
        } for i in o.items],
        "payments":[{"id":p.id,"amount_zar":p.amount_zar,"payment_date":str(p.payment_date),"method":p.method} for p in o.payments]
    }

@router.get("/orders")
def list_orders(status: Optional[str]=None, db: Session=Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Order)
    if status: q = q.filter(Order.status==status)
    return [order_dict(o) for o in q.order_by(Order.order_date.desc()).all()]

@router.post("/orders")
def create_order(data: OrderIn, db: Session=Depends(get_db), current_user=Depends(get_current_user)):
    # Per-day sequence based on the highest existing number for today (collision-safe,
    # unlike a global row count which breaks on concurrent requests)
    prefix = f"ORD-{date.today().strftime('%Y%m%d')}-"
    last = (db.query(Order.order_number)
            .filter(Order.order_number.like(prefix + "%"))
            .order_by(Order.order_number.desc()).first())
    seq = 1
    if last:
        try: seq = int(last[0].rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError): seq = db.query(Order).count() + 1
    order_number = f"{prefix}{seq:03d}"
    o = Order(
        order_number=order_number,
        created_by=current_user.id,
        order_date=date.fromisoformat(data.order_date),
        customer_id=data.customer_id,
        delivery_address=data.delivery_address,
        notes=data.notes,
        discount_amount=data.discount_amount or 0.0,
        discount_pct=data.discount_pct or 0.0,
        discount_reason=data.discount_reason,
        transport_price=data.transport_price or 0.0,
        transport_notes=data.transport_notes,
    )
    db.add(o); db.commit(); db.refresh(o)
    return order_dict(o)

@router.get("/orders/{oid}")
def get_order(oid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    o = db.query(Order).get(oid)
    if not o: raise HTTPException(404)
    return order_dict(o)

@router.put("/orders/{oid}/pricing")
def update_order_pricing(oid: int, body: dict, db: Session=Depends(get_db), _=Depends(get_current_user)):
    """Update discount and transport pricing on an order. Recalculates total."""
    o = db.query(Order).get(oid)
    if not o: raise HTTPException(404)
    if o.status not in ("quote", "confirmed"):
        raise HTTPException(400, "Pricing can only be updated on quote or confirmed orders")
    allowed = {"discount_amount", "discount_pct", "discount_reason", "transport_price", "transport_notes"}
    for k, v in body.items():
        if k in allowed:
            setattr(o, k, v)
    o.total_zar = recalculate_order_total(o)
    db.commit()
    return order_dict(o)


@router.put("/orders/{oid}/status")
def update_status(oid: int, body: dict, db: Session=Depends(get_db), current_user=Depends(get_current_user)):
    o = db.query(Order).get(oid)
    if not o: raise HTTPException(404)
    new_status = body.get("status")
    valid = {"quote","confirmed","dispatched","delivered","cancelled"}
    if new_status not in valid: raise HTTPException(400, "Invalid status")
    old_status = o.status
    o.status = new_status
    db.commit()
    # GL auto-posting
    db.refresh(o)
    if new_status == "confirmed" and old_status != "confirmed":
        gl.post_order_confirmed(db, o, current_user.id)
    elif new_status == "cancelled" and old_status == "confirmed":
        gl.post_order_cancelled(db, o, current_user.id)
    return order_dict(o)

@router.post("/orders/{oid}/items")
def add_item(oid: int, data: OrderItemIn, db: Session=Depends(get_db), _=Depends(get_current_user)):
    o = db.query(Order).get(oid)
    if not o: raise HTTPException(404)
    if o.status != "quote":
        raise HTTPException(400, "Items can only be changed while the order is a quote (the ledger is posted on confirmation)")
    if data.quantity <= 0:
        raise HTTPException(400, "Quantity must be at least 1")
    tier = db.query(PriceTier).get(data.price_tier_id)
    if not tier: raise HTTPException(404, "Tier not found")
    if tier.product_id != data.product_id:
        raise HTTPException(400, "Selected price tier does not belong to that product")
    # Use custom price if provided, otherwise fall back to tier price
    effective_price = data.custom_unit_price if data.custom_unit_price is not None else tier.price_zar
    item = OrderItem(
        order_id=oid,
        product_id=data.product_id,
        price_tier_id=data.price_tier_id,
        quantity=data.quantity,
        unit_price_zar=effective_price,
        line_total_zar=effective_price * data.quantity,
        custom_unit_price=data.custom_unit_price,
        custom_price_reason=data.custom_price_reason,
    )
    db.add(item)
    db.flush()  # assign item.id so it appears in o.items
    o.total_zar = recalculate_order_total(o)
    db.commit()
    return order_dict(o)

@router.delete("/orders/{oid}/items/{iid}")
def remove_item(oid: int, iid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    o = db.query(Order).get(oid)
    if not o: raise HTTPException(404)
    if o.status != "quote":
        raise HTTPException(400, "Items can only be changed while the order is a quote (the ledger is posted on confirmation)")
    item = db.query(OrderItem).filter_by(id=iid, order_id=oid).first()
    if not item: raise HTTPException(404)
    db.delete(item)
    db.flush()
    o.total_zar = recalculate_order_total(o)
    db.commit()
    return order_dict(o)

# ── Deliveries ────────────────────────────────────────────────────────────────
class DeliveryIn(BaseModel):
    order_id: int; scheduled_date: str; driver_name: Optional[str]=None; vehicle_reg: Optional[str]=None
    delivery_type: Optional[str]="customer"        # customer or hardware
    hardware_store_customer_id: Optional[int]=None # linked store account (preferred)
    hardware_store_name: Optional[str]=None        # free-text fallback for stores without an account
    live_location_link: Optional[str]=None         # live tracking link shared with customer

def delivery_dict(d):
    return {
        "id": d.id,
        "order_number": d.order.order_number,
        "customer": d.order.customer.name,
        "delivery_address": d.order.delivery_address,
        "delivery_type": d.delivery_type or "customer",
        "hardware_store_customer_id": d.hardware_store_customer_id,
        "hardware_store_name": (d.hardware_store.name if d.hardware_store_customer_id and d.hardware_store else d.hardware_store_name),
        "scheduled_date": str(d.scheduled_date),
        "actual_date": str(d.actual_date) if d.actual_date else None,
        "driver_name": d.driver_name,
        "vehicle_reg": d.vehicle_reg,
        "status": d.status,
        "live_location_link": d.live_location_link,
    }

@router.get("/deliveries")
def list_deliveries(delivery_type: Optional[str]=None, db: Session=Depends(get_db), _=Depends(get_current_user)):
    q = db.query(Delivery)
    if delivery_type:
        q = q.filter(Delivery.delivery_type==delivery_type)
    return [delivery_dict(d) for d in q.all()]

@router.post("/deliveries")
def create_delivery(data: DeliveryIn, db: Session=Depends(get_db), _=Depends(get_current_user)):
    store_id, store_name = None, None
    if data.delivery_type == "hardware":
        if data.hardware_store_customer_id:
            store = db.query(Customer).get(data.hardware_store_customer_id)
            if not store or store.customer_type != "hardware_store":
                raise HTTPException(400, "Selected store account not found")
            store_id, store_name = store.id, store.name
        elif data.hardware_store_name and data.hardware_store_name.strip():
            store_name = data.hardware_store_name.strip()
            # auto-link if the typed name matches an existing store account
            match = db.query(Customer).filter(Customer.customer_type=="hardware_store",
                                              func.lower(Customer.name)==store_name.lower()).first()
            if match: store_id = match.id
    d = Delivery(
        scheduled_date=date.fromisoformat(data.scheduled_date),
        order_id=data.order_id,
        driver_name=data.driver_name,
        vehicle_reg=data.vehicle_reg,
        delivery_type=data.delivery_type or "customer",
        hardware_store_customer_id=store_id,
        hardware_store_name=store_name,
        live_location_link=data.live_location_link,
    )
    db.add(d); db.commit(); db.refresh(d)
    return delivery_dict(d)

@router.put("/deliveries/{did}")
def update_delivery(did: int, body: dict, db: Session=Depends(get_db), _=Depends(get_current_user)):
    d = db.query(Delivery).get(did)
    if not d: raise HTTPException(404)
    allowed = {"scheduled_date", "actual_date", "driver_name", "vehicle_reg", "status",
               "proof_of_delivery", "live_location_link", "delivery_type", "hardware_store_name",
               "hardware_store_customer_id"}
    date_fields = {"scheduled_date", "actual_date"}
    for k, v in body.items():
        if k in allowed:
            if k in date_fields and isinstance(v, str) and v:
                v = date.fromisoformat(v)
            setattr(d, k, v)
    db.commit()
    return delivery_dict(d)

@router.get("/deliveries/today")
def today_deliveries(db: Session=Depends(get_db), _=Depends(get_current_user)):
    today = date.today()
    ds = db.query(Delivery).filter_by(scheduled_date=today).all()
    return [delivery_dict(d) for d in ds]

@router.get("/deliveries/stats")
def delivery_stats(db: Session=Depends(get_db), _=Depends(get_current_user)):
    total = db.query(Delivery).count()
    customer_count = db.query(Delivery).filter(Delivery.delivery_type=="customer").count()
    hardware_count = db.query(Delivery).filter(Delivery.delivery_type=="hardware").count()
    completed = db.query(Delivery).filter(Delivery.status=="completed").count()
    return {
        "total": total,
        "customer": customer_count,
        "hardware": hardware_count,
        "completed": completed,
        "pending": total - completed,
    }

# ── TLB Bookings ──────────────────────────────────────────────────────────────
DEFAULT_HOURLY_RATE = 1000.0   # R1000/hr
DEFAULT_DAILY_RATE  = 7500.0   # R7500/day
DEFAULT_DIESEL_COST = 3000.0   # R3000 if diesel included

class TLBIn(BaseModel):
    customer_id: int; booking_date: str; hours_billed: float
    rate_type: str; diesel_included: bool=False; notes: Optional[str]=None
    custom_hourly_rate: Optional[float]=None    # override R1000/hr
    custom_daily_rate: Optional[float]=None     # override R7500/day
    custom_rate_reason: Optional[str]=None
    transport_price: Optional[float]=0.0        # transport charge on top of hire
    transport_notes: Optional[str]=None

def tlb_dict(t):
    paid = sum(p.amount_zar for p in t.payments)
    return {
        "id": t.id,
        "customer": t.customer.name,
        "customer_id": t.customer_id,
        "booking_date": str(t.booking_date),
        "hours_billed": t.hours_billed,
        "rate_type": t.rate_type,
        "diesel_included": t.diesel_included,
        "total_zar": t.total_zar,
        "status": t.status,
        "notes": t.notes,
        "custom_hourly_rate": t.custom_hourly_rate,
        "custom_daily_rate": t.custom_daily_rate,
        "custom_rate_reason": t.custom_rate_reason,
        "transport_price": t.transport_price or 0.0,
        "transport_notes": t.transport_notes,
        "paid": paid,
        "balance": t.total_zar - paid,
    }

@router.get("/tlb")
def list_tlb(db: Session=Depends(get_db), _=Depends(get_current_user)):
    return [tlb_dict(t) for t in db.query(TLBBooking).order_by(TLBBooking.booking_date.desc()).all()]

@router.get("/tlb/{tid}")
def get_tlb(tid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    t = db.query(TLBBooking).get(tid)
    if not t: raise HTTPException(404)
    return tlb_dict(t)

@router.post("/tlb")
def create_tlb(data: TLBIn, db: Session=Depends(get_db), current_user=Depends(get_current_user)):
    if data.rate_type == "hourly" and data.hours_billed < 3:
        raise HTTPException(400, "Minimum 3 hours for hourly bookings")
    # Resolve effective rates (custom overrides default)
    hourly_rate = data.custom_hourly_rate if data.custom_hourly_rate is not None else DEFAULT_HOURLY_RATE
    daily_rate  = data.custom_daily_rate  if data.custom_daily_rate  is not None else DEFAULT_DAILY_RATE
    if data.rate_type == "hourly":
        base = data.hours_billed * hourly_rate
    else:
        base = daily_rate
    diesel_cost = DEFAULT_DIESEL_COST if data.diesel_included else 0
    transport = data.transport_price or 0.0
    total = base + diesel_cost + transport
    t = TLBBooking(
        booking_date=date.fromisoformat(data.booking_date),
        customer_id=data.customer_id,
        hours_billed=data.hours_billed,
        rate_type=data.rate_type,
        diesel_included=data.diesel_included,
        notes=data.notes,
        total_zar=total,
        custom_hourly_rate=data.custom_hourly_rate,
        custom_daily_rate=data.custom_daily_rate,
        custom_rate_reason=data.custom_rate_reason,
        transport_price=transport,
        transport_notes=data.transport_notes,
    )
    db.add(t); db.commit(); db.refresh(t)
    gl.post_tlb_booking(db, t, current_user.id)
    return tlb_dict(t)

# ── Store accounts ────────────────────────────────────────────────────────────
def _store_orders(db, store: Customer):
    """All non-cancelled orders on a store's account, oldest first.

    An order belongs to a store's account if EITHER:
      a) the store is the order's customer, or
      b) the order was delivered to that store (linked store account on the
         delivery, or a legacy free-text store name matching this store).
    """
    seen, out = set(), []
    delivered = (db.query(Order).join(Delivery, Delivery.order_id == Order.id)
                 .filter((Delivery.hardware_store_customer_id == store.id) |
                         ((Delivery.hardware_store_customer_id.is_(None)) &
                          (func.lower(func.trim(Delivery.hardware_store_name)) == store.name.strip().lower())))
                 .all())
    for o in list(store.orders) + delivered:
        if o.id in seen or o.status == "cancelled": continue
        seen.add(o.id); out.append(o)
    out.sort(key=lambda o: (o.order_date, o.id))
    return out

def _open_orders_for(db, store: Customer):
    """Store's unpaid orders, oldest first, with balances."""
    out = []
    for o in _store_orders(db, store):
        bal = round(o.total_zar - sum(p.amount_zar for p in o.payments), 2)
        if bal > 0.009:
            out.append((o, bal))
    return out

def _is_hardware_order(o):
    """An order counts as hardware-channel if placed by a store account
    or delivered to a hardware store (incl. legacy free-text store deliveries)."""
    if o.customer and o.customer.customer_type == "hardware_store": return True
    d_ = o.delivery
    return bool(d_ and d_.delivery_type == "hardware")

REVENUE_STATUSES = ("confirmed", "delivered")

@router.get("/stores/revenue-summary")
def store_revenue_summary(db: Session=Depends(get_db), _=Depends(get_current_user)):
    """Hardware-channel revenue (orders placed by a store OR delivered to a store)
    vs direct revenue, for confirmed/delivered orders only."""
    orders = db.query(Order).filter(Order.status.in_(REVENUE_STATUSES)).all()
    is_hardware = _is_hardware_order
    t = date.today()
    month_start = t.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    year_start = t.replace(month=1, day=1)
    buckets = {"this_month": lambda d_: d_ >= month_start,
               "last_month": lambda d_: last_month_start <= d_ <= last_month_end,
               "ytd": lambda d_: d_ >= year_start,
               "all_time": lambda d_: True}
    out = {}
    for name, f in buckets.items():
        hw = sum(o.total_zar for o in orders if f(o.order_date) and is_hardware(o))
        total = sum(o.total_zar for o in orders if f(o.order_date))
        out[name] = {"hardware": round(hw, 2), "direct": round(total - hw, 2),
                     "total": round(total, 2),
                     "hardware_share": round(hw / total, 4) if total else 0}
    return out

@router.get("/stores/revenue-monthly")
def store_revenue_monthly(months: int=12, db: Session=Depends(get_db), _=Depends(get_current_user)):
    """Month-by-month hardware vs direct revenue for the last N months (default 12)."""
    months = max(1, min(months, 36))
    t = date.today()
    # build the month keys, oldest first
    keys = []
    y, m = t.year, t.month
    for _i in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0: y, m = y - 1, 12
    keys.reverse()
    start = date(int(keys[0][:4]), int(keys[0][5:7]), 1)
    buckets = {k: {"hardware": 0.0, "direct": 0.0} for k in keys}
    orders = (db.query(Order).filter(Order.status.in_(REVENUE_STATUSES),
                                     Order.order_date >= start).all())
    for o in orders:
        k = o.order_date.strftime("%Y-%m")
        if k not in buckets: continue
        buckets[k]["hardware" if _is_hardware_order(o) else "direct"] += o.total_zar
    out = []
    for k in keys:
        hw, dr = round(buckets[k]["hardware"], 2), round(buckets[k]["direct"], 2)
        total = round(hw + dr, 2)
        out.append({"month": k,
                    "label": date(int(k[:4]), int(k[5:7]), 1).strftime("%b %Y"),
                    "hardware": hw, "direct": dr, "total": total,
                    "hardware_share": round(hw / total, 4) if total else 0})
    return out

@router.get("/stores/unlinked-names")
def unlinked_store_names(db: Session=Depends(get_db), _=Depends(get_current_user)):
    """Distinct free-text store names on deliveries that have no store account yet."""
    rows = (db.query(Delivery.hardware_store_name)
            .filter(Delivery.hardware_store_customer_id.is_(None),
                    Delivery.hardware_store_name.isnot(None)).distinct().all())
    names = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})
    existing = {(c.name or "").strip().lower() for c in db.query(Customer).all()}
    return {"names": [n for n in names if n.lower() not in existing]}

@router.post("/stores/import-names")
def import_store_names(db: Session=Depends(get_db), _=Depends(get_current_user)):
    """Create a store account for each unlinked delivery store name and link those deliveries."""
    created, linked = [], 0
    rows = (db.query(Delivery).filter(Delivery.hardware_store_customer_id.is_(None),
                                      Delivery.hardware_store_name.isnot(None)).all())
    for d in rows:
        name = (d.hardware_store_name or "").strip()
        if not name: continue
        c = db.query(Customer).filter(func.lower(Customer.name)==name.lower()).first()
        if not c:
            c = Customer(name=name, customer_type="hardware_store")
            db.add(c); db.flush()
            created.append(name)
        elif c.customer_type != "hardware_store":
            c.customer_type = "hardware_store"  # promote existing customer to a store account
        d.hardware_store_customer_id = c.id
        linked += 1
    db.commit()
    return {"created": created, "linked_deliveries": linked}

@router.get("/stores")
def list_store_accounts(db: Session=Depends(get_db), _=Depends(get_current_user)):
    stores = db.query(Customer).filter(Customer.customer_type=="hardware_store").order_by(Customer.name).all()
    result = []
    for c in stores:
        active = _store_orders(db, c)
        invoiced = sum(o.total_zar for o in active)
        paid = sum(p.amount_zar for o in active for p in o.payments)
        open_orders = _open_orders_for(db, c)
        oldest_days = max(((date.today() - o.order_date).days for o, _ in open_orders), default=0)
        last_pay = max((p.payment_date for o in active for p in o.payments), default=None)
        result.append({
            "id": c.id, "name": c.name, "phone": c.phone,
            "orders": len(active), "open_orders": len(open_orders),
            "invoiced": round(invoiced, 2), "paid": round(paid, 2),
            "balance": round(invoiced - paid, 2),
            "oldest_unpaid_days": oldest_days,
            "last_payment": str(last_pay) if last_pay else None,
        })
    result.sort(key=lambda r: -r["balance"])
    return result

@router.get("/stores/{cid}/statement")
def store_statement(cid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    c = db.query(Customer).get(cid)
    if not c: raise HTTPException(404, "Customer not found")
    orders, payments = [], []
    for o in _store_orders(db, c):
        paid = sum(p.amount_zar for p in o.payments)
        orders.append({"id":o.id,"order_number":o.order_number,"order_date":str(o.order_date),
                       "status":o.status,"total_zar":o.total_zar,"paid":round(paid,2),
                       "balance":round(o.total_zar-paid,2),
                       "age_days":(date.today()-o.order_date).days,
                       "via_delivery": o.customer_id != c.id,
                       "end_customer": o.customer.name if o.customer_id != c.id else None})
        for p in o.payments:
            payments.append({"id":p.id,"payment_date":str(p.payment_date),"amount_zar":p.amount_zar,
                             "method":p.method,"reference":p.reference,"order_number":o.order_number})
    payments.sort(key=lambda p: p["payment_date"], reverse=True)
    invoiced = sum(o["total_zar"] for o in orders); paid = sum(o["paid"] for o in orders)
    return {"id":c.id,"name":c.name,"phone":c.phone,"customer_type":c.customer_type or "individual",
            "invoiced":round(invoiced,2),"paid":round(paid,2),"balance":round(invoiced-paid,2),
            "orders":orders,"payments":payments}

# ── Payments ──────────────────────────────────────────────────────────────────
class PaymentIn(BaseModel):
    order_id: Optional[int]=None; tlb_booking_id: Optional[int]=None
    customer_id: Optional[int]=None  # account payment: allocated oldest-first across open orders
    amount_zar: float; payment_date: str; method: str; reference: Optional[str]=None

@router.post("/payments")
def create_payment(data: PaymentIn, db: Session=Depends(get_db), current_user=Depends(get_current_user)):
    if data.amount_zar <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    targets = [bool(data.order_id), bool(data.tlb_booking_id), bool(data.customer_id)]
    if sum(targets) != 1:
        raise HTTPException(400, "Payment must be linked to exactly one of: an order, a TLB booking, or a customer account")

    # ── Account payment: allocate oldest-first, partial amounts welcome ──
    if data.customer_id:
        c = db.query(Customer).get(data.customer_id)
        if not c: raise HTTPException(404, "Customer not found")
        open_orders = _open_orders_for(db, c)
        if not open_orders:
            raise HTTPException(400, f"{c.name} has no outstanding balance")
        total_owed = round(sum(b for _, b in open_orders), 2)
        if data.amount_zar > total_owed + 0.009:
            raise HTTPException(400, f"Amount exceeds outstanding balance of R{total_owed:,.2f}. "
                                     f"Reduce the amount (overpayments/credits are not supported).")
        pay_date = date.fromisoformat(data.payment_date)
        remaining = round(data.amount_zar, 2)
        allocations = []
        for o, bal in open_orders:
            if remaining <= 0.009: break
            alloc = round(min(remaining, bal), 2)
            p = Payment(order_id=o.id, amount_zar=alloc, payment_date=pay_date,
                        method=data.method, reference=data.reference, recorded_by=current_user.id)
            db.add(p); db.flush()
            gl.post_payment_received(db, p, current_user.id)
            allocations.append({"order_number": o.order_number, "allocated": alloc,
                                "remaining_on_order": round(bal - alloc, 2)})
            remaining = round(remaining - alloc, 2)
        db.commit()
        return {"account_payment": True, "customer": c.name, "amount_zar": data.amount_zar,
                "allocations": allocations,
                "balance_after": round(total_owed - data.amount_zar, 2)}

    # ── Single order / TLB payment (partial amounts always allowed) ──
    if data.order_id and not db.query(Order).get(data.order_id):
        raise HTTPException(404, "Order not found")
    if data.tlb_booking_id and not db.query(TLBBooking).get(data.tlb_booking_id):
        raise HTTPException(404, "TLB booking not found")
    p = Payment(payment_date=date.fromisoformat(data.payment_date), recorded_by=current_user.id,
                **data.dict(exclude={"payment_date", "customer_id"}))
    db.add(p); db.commit(); db.refresh(p)
    gl.post_payment_received(db, p, current_user.id)
    return {"id":p.id,"amount_zar":p.amount_zar}

@router.get("/payments")
def list_payments(db: Session=Depends(get_db), _=Depends(get_current_user)):
    return [{"id":p.id,"amount_zar":p.amount_zar,"payment_date":str(p.payment_date),"method":p.method,
             "reference":p.reference,"order_id":p.order_id,
             "linked_to": (p.order.order_number if p.order else (f"TLB-{p.tlb_booking_id}" if p.tlb_booking_id else "–")),
             "customer": (p.order.customer.name if p.order else (p.tlb_booking.customer.name if p.tlb_booking else "–"))
             } for p in db.query(Payment).order_by(Payment.payment_date.desc()).all()]

# ── GL ────────────────────────────────────────────────────────────────────────
@router.get("/gl/accounts")
def get_accounts(db: Session=Depends(get_db), _=Depends(get_current_user)):
    return [{"id":a.id,"code":a.code,"name":a.name,"account_type":a.account_type,"normal_balance":a.normal_balance} for a in db.query(Account).order_by(Account.code).all()]

@router.get("/gl/trial-balance")
def trial_balance(db: Session=Depends(get_db), _=Depends(get_current_user)):
    return gl.get_trial_balance(db)

@router.get("/gl/profit-loss")
def profit_loss(start: Optional[str]=None, end: Optional[str]=None, db: Session=Depends(get_db), _=Depends(get_current_user)):
    return gl.get_profit_loss(db, date.fromisoformat(start) if start else None, date.fromisoformat(end) if end else None)

@router.get("/gl/ar-aging")
def ar_aging(db: Session=Depends(get_db), _=Depends(get_current_user)):
    return gl.get_ar_aging(db)

@router.get("/gl/journal")
def journal(db: Session=Depends(get_db), _=Depends(get_current_user)):
    entries = db.query(JournalEntry).order_by(JournalEntry.entry_date.desc()).limit(500).all()
    return [{"id":e.id,"transaction_ref":e.transaction_ref,"entry_date":str(e.entry_date),
             "account_code":e.account.code,"account_name":e.account.name,
             "debit_zar":e.debit_zar,"credit_zar":e.credit_zar,"description":e.description} for e in entries]

class ManualEntryLine(BaseModel):
    account_id: int; debit_zar: float=0; credit_zar: float=0; description: str

class ManualJournalIn(BaseModel):
    entry_date: str; lines: list[ManualEntryLine]

@router.post("/gl/journal")
def post_manual_journal(data: ManualJournalIn, db: Session=Depends(get_db), current_user=Depends(require_admin)):
    total_debit = sum(l.debit_zar for l in data.lines)
    total_credit = sum(l.credit_zar for l in data.lines)
    if abs(total_debit - total_credit) > 0.01:
        raise HTTPException(400, "Debits must equal credits")
    ref = f"MAN-{date.today().strftime('%Y%m%d')}-{db.query(JournalEntry).count()+1}"
    entries = [JournalEntry(transaction_ref=ref, entry_date=date.fromisoformat(data.entry_date),
                            account_id=l.account_id, debit_zar=l.debit_zar, credit_zar=l.credit_zar,
                            description=l.description, source_type="manual", posted_by=current_user.id, is_manual=True)
               for l in data.lines]
    db.add_all(entries); db.commit()
    return {"ref":ref,"entries":len(entries)}

# ── Address Lookup ────────────────────────────────────────────────────────────
@router.get("/addresses/lookup")
def lookup_addresses(q: str = "", db: Session = Depends(get_db), _ = Depends(get_current_user)):
    """Search past order delivery addresses and return associated live link + transport costs."""
    if len(q.strip()) < 2:
        return []
    orders = (
        db.query(Order)
        .filter(Order.delivery_address.ilike(f"%{q.strip()}%"))
        .order_by(Order.order_date.desc())
        .limit(100)
        .all()
    )
    seen = {}
    for o in orders:
        addr = (o.delivery_address or "").strip()
        if not addr:
            continue
        if addr not in seen:
            seen[addr] = {
                "address": addr,
                "live_location_link": None,
                "transport_price": o.transport_price or 0.0,
                "transport_notes": o.transport_notes,
                "last_customer": o.customer.name,
                "last_used": str(o.order_date),
            }
        # Attach the most recent live_location_link for this address
        if seen[addr]["live_location_link"] is None and o.delivery:
            link = o.delivery.live_location_link
            if link:
                seen[addr]["live_location_link"] = link
    return list(seen.values())[:10]

# ── Reports & Export ──────────────────────────────────────────────────────────
@router.get("/reports/summary")
def summary(db: Session=Depends(get_db), _=Depends(get_current_user)):
    total_rev = db.query(func.coalesce(func.sum(Order.total_zar),0)).filter(Order.status!="cancelled").scalar()
    total_paid = db.query(func.coalesce(func.sum(Payment.amount_zar),0)).scalar()
    order_count = db.query(Order).count()
    customer_count = db.query(Customer).count()
    return {"total_revenue":total_rev,"total_paid":total_paid,"outstanding":total_rev-total_paid,
            "order_count":order_count,"customer_count":customer_count}

@router.get("/reports/top-customers")
def top_customers(limit: int=10, db: Session=Depends(get_db), _=Depends(get_current_user)):
    """Return ranked customer list with revenue, order count, recency, and status."""
    from collections import defaultdict
    orders = db.query(Order).filter(Order.status != "cancelled").all()
    payments = db.query(Payment).all()
    today = date.today()

    cust_data = defaultdict(lambda: {
        "id": None, "orders": 0, "revenue": 0.0,
        "paid": 0.0, "first": None, "last": None
    })
    for o in orders:
        c = cust_data[o.customer.name]
        c["id"] = o.customer_id
        c["orders"] += 1
        c["revenue"] += o.total_zar
        if not c["first"] or o.order_date < c["first"]: c["first"] = o.order_date
        if not c["last"]  or o.order_date > c["last"]:  c["last"]  = o.order_date

    # Tally payments per customer via order linkage
    pay_by_customer = defaultdict(float)
    for p in payments:
        if p.order_id:
            o = next((x for x in orders if x.id == p.order_id), None)
            if o:
                pay_by_customer[o.customer.name] += p.amount_zar

    result = []
    total_rev = sum(c["revenue"] for c in cust_data.values()) or 1
    for rank, (name, c) in enumerate(
        sorted(cust_data.items(), key=lambda x: x[1]["revenue"], reverse=True), 1
    ):
        days_since = (today - c["last"]).days if c["last"] else 9999
        avg_order = c["revenue"] / c["orders"] if c["orders"] else 0
        span_mo = max(((c["last"] - c["first"]).days / 30.0), 1) if c["first"] and c["last"] else 1
        opm = c["orders"] / span_mo
        paid = pay_by_customer[name]
        balance = c["revenue"] - paid
        rev_share = c["revenue"] / total_rev

        if   c["orders"] == 1 and days_since <= 60:  status = "New"
        elif days_since <= 30:                        status = "Active"
        elif days_since <= 60:                        status = "Quiet"
        elif days_since <= 90:                        status = "At Risk"
        elif days_since <= 180:                       status = "Lapsing"
        else:                                         status = "Lapsed"

        result.append({
            "rank": rank, "id": c["id"], "name": name,
            "orders": c["orders"], "revenue": round(c["revenue"], 2),
            "avg_order": round(avg_order, 2), "paid": round(paid, 2),
            "balance": round(balance, 2), "rev_share": round(rev_share, 4),
            "orders_per_month": round(opm, 2), "days_since_last": days_since,
            "first_order": str(c["first"]) if c["first"] else None,
            "last_order": str(c["last"]) if c["last"] else None,
            "status": status,
        })
        if rank >= limit:
            break

    return result

# ── Laybuys ───────────────────────────────────────────────────────────────────
DEFAULT_LAYBUY_MONTHS = 3

class LaybuyIn(BaseModel):
    order_id: int
    months: Optional[int] = DEFAULT_LAYBUY_MONTHS   # default 3, fully overridable
    start_date: str
    notes: Optional[str] = None

def laybuy_dict(lb):
    paid_amount = sum(i.amount for i in lb.installments if i.paid)
    return {
        "id": lb.id,
        "order_id": lb.order_id,
        "order_number": lb.order.order_number if lb.order else None,
        "customer_name": lb.order.customer.name if lb.order and lb.order.customer else None,
        "months": lb.months,
        "start_date": str(lb.start_date),
        "total_amount": lb.total_amount,
        "installment_amount": lb.installment_amount,
        "paid_amount": paid_amount,
        "balance": lb.total_amount - paid_amount,
        "notes": lb.notes,
        "status": lb.status,
        "installments": [{
            "id": i.id,
            "installment_number": i.installment_number,
            "due_date": str(i.due_date),
            "amount": i.amount,
            "paid": i.paid,
            "paid_date": str(i.paid_date) if i.paid_date else None,
        } for i in sorted(lb.installments, key=lambda x: x.installment_number)],
    }

@router.get("/laybuys")
def list_laybuys(db: Session=Depends(get_db), _=Depends(get_current_user)):
    return [laybuy_dict(lb) for lb in db.query(Laybuy).order_by(Laybuy.created_at.desc()).all()]

@router.get("/laybuys/{lid}")
def get_laybuy(lid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    lb = db.query(Laybuy).get(lid)
    if not lb: raise HTTPException(404)
    return laybuy_dict(lb)

@router.post("/laybuys")
def create_laybuy(data: LaybuyIn, db: Session=Depends(get_db), current_user=Depends(get_current_user)):
    order = db.query(Order).get(data.order_id)
    if not order: raise HTTPException(404, "Order not found")
    if order.total_zar <= 0:
        raise HTTPException(400, "Order has no total to put on lay-buy — add items first")
    existing = db.query(Laybuy).filter_by(order_id=data.order_id, status="active").first()
    if existing:
        raise HTTPException(400, f"Order {order.order_number} already has an active lay-buy (LB-{existing.id})")
    months = max(1, data.months or DEFAULT_LAYBUY_MONTHS)
    start = date.fromisoformat(data.start_date)
    base_installment = round(order.total_zar / months, 2)
    # Last installment absorbs any rounding difference
    last_installment = round(order.total_zar - base_installment * (months - 1), 2)
    lb = Laybuy(
        order_id=data.order_id,
        months=months,
        start_date=start,
        total_amount=order.total_zar,
        installment_amount=base_installment,
        notes=data.notes,
        created_by=current_user.id,
    )
    db.add(lb); db.flush()
    for i in range(months):
        due = add_months(start, i)
        amt = base_installment if i < months - 1 else last_installment
        db.add(LaybuyInstallment(
            laybuy_id=lb.id,
            installment_number=i + 1,
            due_date=due,
            amount=amt,
        ))
    db.commit(); db.refresh(lb)
    return laybuy_dict(lb)

@router.put("/laybuys/{lid}/installments/{iid}/pay")
def mark_installment_paid(lid: int, iid: int, body: dict, db: Session=Depends(get_db), _=Depends(get_current_user)):
    inst = db.query(LaybuyInstallment).filter_by(id=iid, laybuy_id=lid).first()
    if not inst: raise HTTPException(404)
    inst.paid = True
    inst.paid_date = date.fromisoformat(body.get("paid_date", str(date.today())))
    db.flush()
    lb = db.query(Laybuy).get(lid)
    db.refresh(lb)
    if all(i.paid for i in lb.installments):
        lb.status = "completed"
    db.commit(); db.refresh(lb)
    return laybuy_dict(lb)

@router.put("/laybuys/{lid}/cancel")
def cancel_laybuy(lid: int, db: Session=Depends(get_db), _=Depends(get_current_user)):
    lb = db.query(Laybuy).get(lid)
    if not lb: raise HTTPException(404)
    lb.status = "cancelled"
    db.commit()
    return laybuy_dict(lb)
