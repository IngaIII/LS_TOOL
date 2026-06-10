import sys
import os

# Portable paths — works wherever you put the folder (Windows, Mac, Linux)
_HERE = os.path.dirname(os.path.abspath(__file__))

# Load .env file when running locally (ignored on Railway where vars are set in the dashboard)
_env_file = os.path.join(_HERE, ".env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "gl"))

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import engine, get_db, SessionLocal
import models
from auth import get_current_user
from routers.api import router
from seed import seed_database
from exports.excel import generate_full_report

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Logistics Internal System", version="1.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

@app.get("/api/v1/export/full-report.xlsx")
def export_full_report(db: Session = Depends(get_db), _=Depends(get_current_user)):
    output = generate_full_report(db)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=logistics-report.xlsx"}
    )

def run_migrations():
    """Add new columns to existing tables without destroying data."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE deliveries ADD COLUMN delivery_type VARCHAR DEFAULT 'customer'",
        "ALTER TABLE deliveries ADD COLUMN live_location_link VARCHAR",
        "ALTER TABLE deliveries ADD COLUMN hardware_store_name VARCHAR",
        "ALTER TABLE customers ADD COLUMN customer_type VARCHAR DEFAULT 'individual'",
        "ALTER TABLE deliveries ADD COLUMN hardware_store_customer_id INTEGER",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists
        # Data migration: the GL service posts transport revenue to account 4095,
        # but older databases were seeded without it (causing unbalanced journals).
        # Only patch databases that already have a chart of accounts — on a fresh
        # install the seeder creates the full chart including 4095.
        try:
            has_accounts = conn.execute(text("SELECT COUNT(*) FROM accounts")).scalar()
            if has_accounts:
                exists = conn.execute(text("SELECT 1 FROM accounts WHERE code='4095'")).first()
                if not exists:
                    conn.execute(text(
                        "INSERT INTO accounts (code, name, account_type, normal_balance, is_active) "
                        "VALUES ('4095', 'Transport & Delivery Revenue', 'revenue', 'credit', 1)"
                    ))
                    conn.commit()
        except Exception:
            pass  # accounts table not created yet; seed will handle it
        # Link legacy hardware-store deliveries (free-text name) to store accounts
        # whose customer name matches, so their orders count on the right account.
        try:
            conn.execute(text(
                "UPDATE deliveries SET hardware_store_customer_id = ("
                "  SELECT c.id FROM customers c WHERE c.customer_type='hardware_store' "
                "  AND LOWER(TRIM(c.name)) = LOWER(TRIM(deliveries.hardware_store_name)) LIMIT 1"
                ") WHERE hardware_store_customer_id IS NULL AND hardware_store_name IS NOT NULL"
            ))
            conn.commit()
        except Exception:
            pass

@app.on_event("startup")
def startup():
    run_migrations()
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()

# Serve frontend — looks for frontend_dist next to the backend folder
FRONTEND_DIST = os.path.join(_HERE, "..", "frontend_dist")
FRONTEND_DIST = os.path.abspath(FRONTEND_DIST)

if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            return None
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
