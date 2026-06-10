from datetime import date
from sqlalchemy.orm import Session
from models import Account, JournalEntry, Order, TLBBooking

CATEGORY_ACCOUNT_MAP = {
    "brick": "4000",
    "block": "4000",
    "building": "4010",
    "sabunge": "4020",
    "plaster": "4030",
    "river_sand": "4040",
    "stone": "4050",
    "cement": "4060",
    "tlb": "4070",
    "diesel": "4080",
    "water": "4090",
    "transport": "4095",  # transport / delivery revenue account
}

def get_account(db: Session, code: str) -> Account:
    return db.query(Account).filter_by(code=code).first()

def post_order_confirmed(db: Session, order: Order, user_id: int):
    """Post journal entries when an order is confirmed."""
    ar_account = get_account(db, "1100")
    entry_date = date.today()

    # Group line totals by revenue account (using actual unit_price_zar which may be custom)
    revenue_map = {}
    for item in order.items:
        cat = item.product.category
        rev_code = CATEGORY_ACCOUNT_MAP.get(cat, "4000")
        revenue_map[rev_code] = revenue_map.get(rev_code, 0) + item.line_total_zar

    # Add transport revenue if present
    transport = order.transport_price or 0.0
    if transport > 0:
        transport_account_code = "4095"
        revenue_map[transport_account_code] = revenue_map.get(transport_account_code, 0) + transport

    # Compute items + transport subtotal
    items_transport_subtotal = sum(revenue_map.values())

    # Compute discount amount to deduct
    discount = 0.0
    if order.discount_pct and order.discount_pct > 0:
        discount += items_transport_subtotal * (order.discount_pct / 100)
    if order.discount_amount and order.discount_amount > 0:
        discount += order.discount_amount
    discount = min(discount, items_transport_subtotal)  # can't exceed total

    entries = []
    # Debit AR for confirmed order total (post-discount)
    entries.append(JournalEntry(
        transaction_ref=order.order_number,
        entry_date=entry_date,
        account_id=ar_account.id,
        debit_zar=order.total_zar,
        credit_zar=0.0,
        description=f"Order {order.order_number} confirmed - {order.customer.name}",
        source_type="order",
        source_id=order.id,
        posted_by=user_id,
        is_manual=False,
    ))

    # Credit each revenue account (proportionally reduced by discount if applicable)
    discount_remaining = discount
    revenue_items = list(revenue_map.items())
    for idx, (code, amount) in enumerate(revenue_items):
        rev_account = get_account(db, code)
        if rev_account is None:
            continue
        # Spread discount proportionally across revenue lines
        if discount > 0 and items_transport_subtotal > 0:
            line_discount = (amount / items_transport_subtotal) * discount
        else:
            line_discount = 0.0
        net_amount = amount - line_discount
        entries.append(JournalEntry(
            transaction_ref=order.order_number,
            entry_date=entry_date,
            account_id=rev_account.id,
            debit_zar=0.0,
            credit_zar=max(net_amount, 0.0),
            description=f"Revenue - Order {order.order_number}" + (f" (transport)" if code == "4095" else ""),
            source_type="order",
            source_id=order.id,
            posted_by=user_id,
            is_manual=False,
        ))

    db.add_all(entries)
    db.commit()

def post_order_cancelled(db: Session, order: Order, user_id: int):
    """Reverse journal entries when an order is cancelled."""
    ar_account = get_account(db, "1100")
    entry_date = date.today()
    ref = f"{order.order_number}-REV"

    revenue_map = {}
    for item in order.items:
        cat = item.product.category
        rev_code = CATEGORY_ACCOUNT_MAP.get(cat, "4000")
        revenue_map[rev_code] = revenue_map.get(rev_code, 0) + item.line_total_zar

    transport = order.transport_price or 0.0
    if transport > 0:
        revenue_map["4095"] = revenue_map.get("4095", 0) + transport

    items_transport_subtotal = sum(revenue_map.values())
    discount = 0.0
    if order.discount_pct and order.discount_pct > 0:
        discount += items_transport_subtotal * (order.discount_pct / 100)
    if order.discount_amount and order.discount_amount > 0:
        discount += order.discount_amount

    entries = []
    entries.append(JournalEntry(
        transaction_ref=ref, entry_date=entry_date,
        account_id=ar_account.id, debit_zar=0.0, credit_zar=order.total_zar,
        description=f"Reversal - Order {order.order_number} cancelled",
        source_type="order", source_id=order.id, posted_by=user_id, is_manual=False,
    ))
    for code, amount in revenue_map.items():
        rev_account = get_account(db, code)
        if rev_account is None:
            continue
        if discount > 0 and items_transport_subtotal > 0:
            line_discount = (amount / items_transport_subtotal) * discount
        else:
            line_discount = 0.0
        net_amount = amount - line_discount
        entries.append(JournalEntry(
            transaction_ref=ref, entry_date=entry_date,
            account_id=rev_account.id, debit_zar=max(net_amount, 0.0), credit_zar=0.0,
            description=f"Reversal - Revenue for Order {order.order_number}",
            source_type="order", source_id=order.id, posted_by=user_id, is_manual=False,
        ))
    db.add_all(entries)
    db.commit()

def post_payment_received(db: Session, payment, user_id: int):
    """Post journal entries when payment is received."""
    cash_account = get_account(db, "1000" if payment.method == "cash" else "1010")
    ar_account = get_account(db, "1100")
    ref = f"PAY-{payment.id}"

    entries = [
        JournalEntry(
            transaction_ref=ref, entry_date=payment.payment_date,
            account_id=cash_account.id, debit_zar=payment.amount_zar, credit_zar=0.0,
            description=f"Payment received ({payment.method}){' ref: ' + payment.reference if payment.reference else ''}",
            source_type="payment", source_id=payment.id, posted_by=user_id, is_manual=False,
        ),
        JournalEntry(
            transaction_ref=ref, entry_date=payment.payment_date,
            account_id=ar_account.id, debit_zar=0.0, credit_zar=payment.amount_zar,
            description=f"AR cleared - Payment received",
            source_type="payment", source_id=payment.id, posted_by=user_id, is_manual=False,
        ),
    ]
    db.add_all(entries)
    db.commit()

def post_tlb_booking(db: Session, booking: TLBBooking, user_id: int):
    """Post journal entries for TLB booking (supports custom rates and transport)."""
    ar_account = get_account(db, "1100")
    tlb_account = get_account(db, "4070")
    diesel_account = get_account(db, "4080")
    transport_account = get_account(db, "4095")
    ref = f"TLB-{booking.id}"
    entry_date = booking.booking_date

    diesel_cost = 3000 if booking.diesel_included else 0
    transport = booking.transport_price or 0.0
    tlb_amount = booking.total_zar - diesel_cost - transport

    entries = [
        JournalEntry(
            transaction_ref=ref, entry_date=entry_date,
            account_id=ar_account.id, debit_zar=booking.total_zar, credit_zar=0.0,
            description=f"TLB Hire - {booking.customer.name}"
                        + (f" [custom rate]" if booking.custom_hourly_rate or booking.custom_daily_rate else ""),
            source_type="tlb", source_id=booking.id, posted_by=user_id, is_manual=False,
        ),
        JournalEntry(
            transaction_ref=ref, entry_date=entry_date,
            account_id=tlb_account.id, debit_zar=0.0, credit_zar=tlb_amount,
            description=f"TLB Hire Revenue",
            source_type="tlb", source_id=booking.id, posted_by=user_id, is_manual=False,
        ),
    ]
    if booking.diesel_included:
        entries.append(JournalEntry(
            transaction_ref=ref, entry_date=entry_date,
            account_id=diesel_account.id, debit_zar=0.0, credit_zar=diesel_cost,
            description=f"Diesel Security Income",
            source_type="tlb", source_id=booking.id, posted_by=user_id, is_manual=False,
        ))
    if transport > 0 and transport_account:
        entries.append(JournalEntry(
            transaction_ref=ref, entry_date=entry_date,
            account_id=transport_account.id, debit_zar=0.0, credit_zar=transport,
            description=f"Transport Revenue - TLB-{booking.id}"
                        + (f" ({booking.transport_notes})" if booking.transport_notes else ""),
            source_type="tlb", source_id=booking.id, posted_by=user_id, is_manual=False,
        ))
    db.add_all(entries)
    db.commit()

def get_trial_balance(db: Session):
    from sqlalchemy import func
    from models import JournalEntry, Account
    accounts = db.query(Account).filter_by(is_active=True).order_by(Account.code).all()
    result = []
    for acc in accounts:
        totals = db.query(
            func.coalesce(func.sum(JournalEntry.debit_zar), 0),
            func.coalesce(func.sum(JournalEntry.credit_zar), 0)
        ).filter(JournalEntry.account_id == acc.id).first()
        result.append({
            "code": acc.code, "name": acc.name,
            "account_type": acc.account_type,
            "normal_balance": acc.normal_balance,
            "total_debit": totals[0], "total_credit": totals[1],
            "net": totals[0] - totals[1]
        })
    return result

def get_profit_loss(db: Session, start_date=None, end_date=None):
    from sqlalchemy import func
    from models import JournalEntry, Account
    query = db.query(Account, func.coalesce(func.sum(JournalEntry.credit_zar), 0) - func.coalesce(func.sum(JournalEntry.debit_zar), 0)).\
        outerjoin(JournalEntry, Account.id == JournalEntry.account_id).\
        filter(Account.account_type.in_(["revenue", "expense"]))
    if start_date:
        query = query.filter(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.entry_date <= end_date)
    query = query.group_by(Account.id).order_by(Account.code)
    rows = query.all()
    revenue, expenses = [], []
    for acc, net in rows:
        item = {"code": acc.code, "name": acc.name, "amount": net}
        if acc.account_type == "revenue":
            revenue.append(item)
        else:
            expenses.append({"code": acc.code, "name": acc.name, "amount": -net})
    total_revenue = sum(r["amount"] for r in revenue)
    total_expenses = sum(e["amount"] for e in expenses)
    return {
        "revenue": revenue, "expenses": expenses,
        "total_revenue": total_revenue, "total_expenses": total_expenses,
        "net_profit": total_revenue - total_expenses
    }

def get_ar_aging(db: Session):
    from models import Order, Payment, Customer
    from sqlalchemy import func
    today = date.today()
    orders = db.query(Order).filter(Order.status.in_(["confirmed","dispatched","delivered"])).all()
    result = []
    for order in orders:
        paid = sum(p.amount_zar for p in order.payments)
        balance = order.total_zar - paid
        if balance <= 0:
            continue
        age = (today - order.order_date).days
        row = {
            "customer": order.customer.name,
            "order_number": order.order_number,
            "order_date": str(order.order_date),
            "total": order.total_zar,
            "paid": paid,
            "balance": balance,
            "current": balance if age <= 30 else 0,
            "days_31_60": balance if 31 <= age <= 60 else 0,
            "days_61_90": balance if 61 <= age <= 90 else 0,
            "days_90_plus": balance if age > 90 else 0,
        }
        result.append(row)
    return result
