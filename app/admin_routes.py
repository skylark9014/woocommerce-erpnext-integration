# =============================
# Admin Panel Routes
# =============================

import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.sync.sync_preview import generate_sync_preview
from app.mapping.mapping_store import load_mapping_raw, save_mapping
from app.sync.product_mapper import (
    build_or_load_mapping,
    apply_overrides,
    map_erp_to_wc_product,
)
from app.erp.erp_fetch import (
    get_erpnext_items,
    get_price_from_pricelist,
    get_default_pricelist,
)
from app.woocommerce.wc_fetch import get_wc_products
from app.woocommerce.woocommerce_api import wc_create, wc_update, wc_delete
from app.utils.compare import needs_update
from app.config import MAPPING_JSON_FILE
from app.sync.product_sync import sync_products

logger = logging.getLogger("uvicorn.error")

# Router with a prefix so every path is under /admin
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Templates dir: app/templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# Static is mounted once in main_app.py -> do NOT mount here


# -----------------------------
# ✅ Admin UI Page
# -----------------------------
@admin_router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_page(request: Request):
    return templates.TemplateResponse("mapping.html", {"request": request})


# -----------------------------
# ✅ Preview Sync (Dry Run)
# -----------------------------
@admin_router.post("/api/preview-sync")
async def preview_sync_handler():
    try:
        return await generate_sync_preview()
    except Exception as e:
        logger.exception("Preview sync failed")
        return {"status": "error", "error": str(e)}


# -----------------------------
# ✅ Mapping CRUD
# -----------------------------
@admin_router.get("/api/mapping")
def get_mapping():
    return load_mapping_raw(MAPPING_JSON_FILE) or {"auto": [], "overrides": []}


@admin_router.put("/api/mapping")
async def save_mapping_handler(payload: dict):
    auto = payload.get("auto")
    overrides = payload.get("overrides", [])
    if auto is None:
        current = load_mapping_raw(MAPPING_JSON_FILE) or {"auto": [], "overrides": []}
        auto = current["auto"]
    save_mapping(MAPPING_JSON_FILE, auto, overrides)
    return {"status": "ok"}


# -----------------------------
# ✅ Utility: Get fresh ERP/WC + mapping
# -----------------------------
def get_fresh_data() -> Tuple[dict, dict, list, list]:
    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping(MAPPING_JSON_FILE, wc_products, erp_items)
    apply_overrides(auto_rows, overrides)
    erp_index = {i["item_code"]: i for i in erp_items}
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}
    return erp_index, wc_index, auto_rows, overrides


# =============================
# 🔁 Bulk Sync Action Endpoints
# =============================

@admin_router.post("/api/bulk-sync/{action}")
async def bulk_sync_action(action: str):
    if action == "create":
        return await bulk_create()
    if action == "update":
        return await bulk_update()
    if action == "delete":
        return await bulk_delete()
    raise HTTPException(status_code=400, detail="Invalid action. Use one of: create, update, delete.")


@admin_router.post("/api/sync/create")
async def bulk_create():
    erp_index, wc_index, auto_rows, overrides = get_fresh_data()
    created, failed = [], []

    for row in auto_rows:
        code = row["erp_item_code"]
        if row.get("wc_product_id") or code in wc_index:
            continue
        price = await get_price_from_pricelist(None, code, "Standard Selling")
        if price is None:
            failed.append(code)
            continue
        try:
            payload = map_erp_to_wc_product(erp_index[code], price)
            wc_p = wc_create("products", payload)
            row.update(
                {
                    "wc_product_id": wc_p["id"],
                    "wc_sku": wc_p.get("sku") or code,
                    "status": "created",
                    "last_price": price,
                    "last_synced": datetime.utcnow().isoformat() + "Z",
                }
            )
            created.append(code)
        except Exception as e:
            logger.error(f"[Create] {code} failed: {e}")
            failed.append(code)

    save_mapping(MAPPING_JSON_FILE, auto_rows, overrides)
    return {"created": created, "failed": failed}


@admin_router.post("/api/sync/update")
async def bulk_update():
    erp_index, wc_index, auto_rows, overrides = get_fresh_data()
    updated, failed = [], []

    for row in auto_rows:
        code = row["erp_item_code"]
        wc_p = wc_index.get(code)
        if not wc_p:
            continue

        price = await get_price_from_pricelist(None, code, "Standard Selling")
        if price is None:
            failed.append(code)
            continue

        desired = map_erp_to_wc_product(erp_index[code], price)

        if needs_update(desired, wc_p):
            try:
                wc_update(f"products/{wc_p['id']}", desired)
                row.update(
                    {
                        "status": "updated",
                        "last_price": price,
                        "last_synced": datetime.utcnow().isoformat() + "Z",
                    }
                )
                updated.append(code)
            except Exception as e:
                logger.error(f"[Update] {code} failed: {e}")
                failed.append(code)

    save_mapping(MAPPING_JSON_FILE, auto_rows, overrides)
    return {"updated": updated, "failed": failed}


@admin_router.post("/api/sync/delete")
async def bulk_delete():
    erp_index, wc_index, auto_rows, overrides = get_fresh_data()
    erp_codes = set(erp_index.keys())
    deleted, failed = [], []

    for sku, wc_p in wc_index.items():
        if sku not in erp_codes:
            try:
                wc_delete(f"products/{wc_p['id']}")
                deleted.append(sku)
            except Exception as e:
                logger.error(f"[Delete] {sku} failed: {e}")
                failed.append(sku)

    return {"deleted": deleted, "failed": failed}


# -----------------------------
# ✅ Full sync endpoint
# -----------------------------
@admin_router.post("/api/full-sync")
async def full_sync_handler(pricelist: str | None = Query(None)):
    if not pricelist:
        pricelist = await get_default_pricelist()
    return await sync_products(pricelist=pricelist)
