# =============================
# ✅ Import and Load .env at startup
# =============================

import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI, APIRouter, Request
import logging
from app.sync.product_sync import sync_products
from app.webhook_handler import handle_webhook

# =============================
# ✅ FastAPI App Initialization
# =============================
logger = logging.getLogger("uvicorn.error")
app = FastAPI()
admin_router = APIRouter()


# ==================================
# ✅ Expose Admin Endpoints for Sync
# ==================================
@admin_router.post("/api/resync")
async def trigger_full_sync():
    """
    Temporary full sync trigger from Admin panel.
    """
    result = await sync_products()
    if result.get("status") == "error":
        return {"status": "error", **result}
    return {"status": "success", **result}


# ======================================
# ✅ Webhook Handler for Woo → ERP Push
# ======================================
@admin_router.post("/webhook")
async def webhook_endpoint(request: Request):
    """
    Handles WooCommerce → ERPNext webhook payloads.
    Validates and triggers Customer + Sales Order creation.
    """
    payload = await request.json()
    try:
        result = await handle_webhook(payload)
        return {"status": "success", **result}
    except Exception as e:
        logger.exception("[Webhook] Failed to process payload")
        return {"status": "error", "error": str(e)}


# =============================
# ✅ Register Admin Routes
# =============================
def register_admin_routes(app: FastAPI):
    app.include_router(admin_router, prefix="/admin")

register_admin_routes(app)

@app.get("/")
def root():
    return {"status": "ok", "message": "WooCommerce ↔ ERPNext integration running"}
