# =============================
# Admin Panel Routes
# =============================

import logging
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.sync_preview import generate_sync_preview
from app.mapping.mapping_store import load_mapping_raw, save_mapping
from app.sync.product_mapper import build_or_load_mapping, apply_overrides, map_erp_to_wc_product, get_price_from_pricelist
from app.erp.erp_fetch import get_erpnext_items
from app.woocommerce.wc_fetch import get_wc_products
from app.woocommerce.woocommerce_api import wc_create, wc_update, wc_delete

logger = logging.getLogger("uvicorn.error")
admin_router = APIRouter()

# Mount static files and setup templates
admin_router.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# -----------------------------
# ✅ Admin UI Page
# -----------------------------
@admin_router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("mapping.html", {"request": request})

# -----------------------------
# ✅ Preview Sync (Dry Run)
# -----------------------------
@admin_router.post("/admin/api/preview-sync")
async def preview_sync_handler():
    try:
        result = await generate_sync_preview()
        return result
    except Exception as e:
        logger.exception("Preview sync failed")
        return {
            "status": "error",
            "error": str(e)
        }

# -----------------------------
# ✅ Utility: Get fresh ERP/WC + mapping
# -----------------------------
def get_fresh_data():
    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping("mapping/product_mapping.json", wc_products, erp_items)
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
    elif action == "update":
        return await bulk_update()
    elif action == "delete":
        return await bulk_delete()
    else:
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
            row.update({
                "wc_product_id": wc_p["id"],
                "status": "created",
                "last_price": price,
                "last_synced": datetime.utcnow().isoformat() + "Z"
            })
            created.append(code)
        except Exception as e:
            logger.error(f"[Create] {code} failed: {e}")
            failed.append(code)

    save_mapping("mapping/product_mapping.json", auto_rows, overrides)
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
        needs_update = any(str(desired.get(fld, "")) != str(wc_p.get(fld, "")) for fld in ("name", "regular_price", "description", "short_description"))
        if needs_update:
            try:
                wc_update(f"products/{wc_p['id']}", desired)
                row.update({
                    "status": "updated",
                    "last_price": price,
                    "last_synced": datetime.utcnow().isoformat() + "Z"
                })
                updated.append(code)
            except Exception as e:
                logger.error(f"[Update] {code} failed: {e}")
                failed.append(code)

    save_mapping("mapping/product_mapping.json", auto_rows, overrides)
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

