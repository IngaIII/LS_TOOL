from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text, ForeignKey, Time
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, default="staff")  # admin or staff
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    customer_type = Column(String, default="individual")  # individual | hardware_store
    phone = Column(String)
    email = Column(String)
    address = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    orders = relationship("Order", back_populates="customer")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    price_tiers = relationship("PriceTier", back_populates="product")

class PriceTier(Base):
    __tablename__ = "price_tiers"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    tier_label = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price_zar = Column(Float, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    product = relationship("Product", back_populates="price_tiers")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_date = Column(Date, nullable=False)
    status = Column(String, default="quote")
    delivery_address = Column(Text)
    notes = Column(Text)
    total_zar = Column(Float, default=0.0)
    # Custom pricing fields
    discount_amount = Column(Float, default=0.0)       # flat rand discount on order total
    discount_pct = Column(Float, default=0.0)          # percentage discount (0-100) applied after items
    discount_reason = Column(String)                    # e.g. "Loyal customer", "Bulk deal"
    transport_price = Column(Float, default=0.0)       # transport / delivery charge added to order
    transport_notes = Column(String)                    # e.g. "Long distance surcharge"
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="order")
    delivery = relationship("Delivery", back_populates="order", uselist=False)

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    price_tier_id = Column(Integer, ForeignKey("price_tiers.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_zar = Column(Float, nullable=False)
    line_total_zar = Column(Float, nullable=False)
    # Custom pricing: if set, overrides the tier price for this line item
    custom_unit_price = Column(Float)                  # override price per unit (None = use tier price)
    custom_price_reason = Column(String)               # reason for override, e.g. "Special deal"
    order = relationship("Order", back_populates="items")
    product = relationship("Product")
    price_tier = relationship("PriceTier")

class Delivery(Base):
    __tablename__ = "deliveries"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    delivery_type = Column(String, default="customer")  # customer or hardware
    hardware_store_name = Column(String)                # legacy free-text store name (kept for old records)
    hardware_store_customer_id = Column(Integer, ForeignKey("customers.id"))  # linked store account
    scheduled_date = Column(Date, nullable=False)
    actual_date = Column(Date)
    driver_name = Column(String)
    vehicle_reg = Column(String)
    status = Column(String, default="scheduled")
    proof_of_delivery = Column(Text)
    live_location_link = Column(String)  # live tracking link shared with customer
    order = relationship("Order", back_populates="delivery")
    hardware_store = relationship("Customer", foreign_keys=[hardware_store_customer_id])

class TLBBooking(Base):
    __tablename__ = "tlb_bookings"
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    booking_date = Column(Date, nullable=False)
    hours_billed = Column(Float, nullable=False)
    rate_type = Column(String, nullable=False)  # hourly or daily
    total_zar = Column(Float, nullable=False)
    diesel_included = Column(Boolean, default=False)
    notes = Column(Text)
    status = Column(String, default="confirmed")
    # Custom pricing fields
    custom_hourly_rate = Column(Float)             # override default R1000/hr (None = use default)
    custom_daily_rate = Column(Float)              # override default R7500/day (None = use default)
    custom_rate_reason = Column(String)            # reason for rate override
    transport_price = Column(Float, default=0.0)   # transport charge added to TLB invoice
    transport_notes = Column(String)               # e.g. "Travel to site surcharge"
    created_at = Column(DateTime, server_default=func.now())
    customer = relationship("Customer")
    payments = relationship("Payment", back_populates="tlb_booking")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    tlb_booking_id = Column(Integer, ForeignKey("tlb_bookings.id"))
    amount_zar = Column(Float, nullable=False)
    payment_date = Column(Date, nullable=False)
    method = Column(String, nullable=False)  # cash, eft, cheque
    reference = Column(String)
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    order = relationship("Order", back_populates="payments")
    tlb_booking = relationship("TLBBooking", back_populates="payments")

class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    account_type = Column(String, nullable=False)  # asset, liability, equity, revenue, expense
    normal_balance = Column(String, nullable=False)  # debit or credit
    is_active = Column(Boolean, default=True)
    description = Column(Text)
    journal_entries = relationship("JournalEntry", back_populates="account")

class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id = Column(Integer, primary_key=True, index=True)
    transaction_ref = Column(String, nullable=False, index=True)
    entry_date = Column(Date, nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    debit_zar = Column(Float, default=0.0)
    credit_zar = Column(Float, default=0.0)
    description = Column(Text, nullable=False)
    source_type = Column(String, nullable=False)  # order, payment, tlb, manual
    source_id = Column(Integer)
    posted_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    posted_at = Column(DateTime, server_default=func.now())
    is_manual = Column(Boolean, default=False)
    account = relationship("Account", back_populates="journal_entries")

class Laybuy(Base):
    __tablename__ = "laybuys"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    months = Column(Integer, default=3)              # default 3, overridable
    start_date = Column(Date, nullable=False)
    total_amount = Column(Float, nullable=False)
    installment_amount = Column(Float, nullable=False)  # total / months
    notes = Column(Text)
    status = Column(String, default="active")        # active, completed, cancelled
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    order = relationship("Order")
    installments = relationship("LaybuyInstallment", back_populates="laybuy", cascade="all, delete-orphan")

class LaybuyInstallment(Base):
    __tablename__ = "laybuy_installments"
    id = Column(Integer, primary_key=True, index=True)
    laybuy_id = Column(Integer, ForeignKey("laybuys.id"), nullable=False)
    installment_number = Column(Integer, nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    paid = Column(Boolean, default=False)
    paid_date = Column(Date)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    laybuy = relationship("Laybuy", back_populates="installments")
