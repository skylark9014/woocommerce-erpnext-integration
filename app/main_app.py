# =============================
# ✅ Import and Load .env at startup
# =============================
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.webhook_handler import handle_webhook
from app.admin_routes import admin_router

logger = logging.getLogger("uvicorn.error")

# =============================
# ✅ FastAPI App Initialization
# =============================
app = FastAPI()

# ---- Static files (served from app/static) ----
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---- Admin router once, with prefix ----
app.include_router(admin_router, prefix="/admin")

@app.get("/")
def root():
    return {"status": "ok", "msg": "WooCommerce ↔ ERPNext integration running"}

# ======================================
# ✅ Webhook Handler (public endpoint)
# ======================================
@app.post("/webhook")
async def webhook_endpoint(request: Request):
    payload = await request.json()
    try:
        result = await handle_webhook(payload)
        return {"status": "success", **result}
    except Exception as e:
        logger.exception("[Webhook] Failed to process payload")
        return {"status": "error", "error": str(e)}
