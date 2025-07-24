# app/admin_routes.py
# =============================
# Admin Panel Routes
# =============================

import logging
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from httpx import HTTPStatusError

from app.sync.sync_preview import generate_sync_preview
from app.mapping.mapping_store import (
    load_mapping_raw,
    save_mapping,
    build_or_load_mapping,
    apply_overrides,
)
from app.sync.product_mapper import map_erp_to_wc_product
from app.sync.image_sync import sync_item_images
from app.erp.erp_fetch import (
    get_price_from_pricelist,
    get_erpnext_items,
    get_default_pricelist,
)
from app.woocommerce.wc_fetch import get_wc_products
from app.woocommerce.woocommerce_api import (
    wc_create,
    wc_update,
    wc_delete,
    wc_search_by_sku,
    wc_force_delete_by_sku,
    wc_regenerate_lookup_table,
    wc_get,  # we'll use this to list trashed products
)
from app.utils.compare import needs_update
from app.sync.product_sync import sync_products
from app.config import MAPPING_JSON_FILE

logger = logging.getLogger("uvicorn.error")
admin_router = APIRouter()

# Templates
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


# ---------------------------------
# Helper: scrub stale Woo mappings
# ---------------------------------
def _scrub_stale_links(auto_rows: list,
                       wc_by_id: Dict[int, dict],
                       wc_by_sku: Dict[str, dict]) -> bool:
    """
    If a row points to a Woo product that no longer exists, clear it so it
    can be recreated. Returns True if anything was changed.
    """
    changed = False
    for r in auto_rows:
        wid = r.get("wc_product_id")
        sku = r.get("wc_sku")
        if wid and wid not in wc_by_id:
            r["wc_product_id"] = None
            r["status"] = "unmatched"
            changed = True
        if sku and sku not in wc_by_sku:
            r["wc_sku"] = None
            r["status"] = "unmatched"
            changed = True
    return changed

async def _ensure_sku_free(sku: str):
    """Delete any lingering product carrying this SKU (any status)."""
    try:
        await wc_force_delete_by_sku(sku)
    except Exception as e:
        logger.warning(f"Cleanup ghost SKU {sku} failed: {e}")


# -----------------------------
# ✅ Admin UI Page
# -----------------------------
@admin_router.get("/", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("mapping.html", {"request": request})


# -----------------------------
# ✅ Preview Sync (Dry Run)
# -----------------------------
@admin_router.post("/api/preview-sync")
async def preview_sync_handler():
    try:
        pricelist = await get_default_pricelist()
        result = await generate_sync_preview(pricelist)
        result["pricelist_used"] = pricelist
        return result
    except Exception as e:
        logger.exception("Preview sync failed")
        return {"status": "error", "error": str(e)}


# -----------------------------
# ✅ Mapping CRUD for UI
# -----------------------------
@admin_router.get("/api/mapping")
async def get_mapping():
    data = load_mapping_raw(MAPPING_JSON_FILE) or {
        "auto": [], "overrides": [], "images": {},
    }
    return data


@admin_router.put("/api/mapping")
async def save_mapping_handler(payload: dict):
    current = load_mapping_raw(MAPPING_JSON_FILE) or {
        "auto": [], "overrides": [], "images": {},
    }

    auto      = payload.get("auto", current["auto"])
    overrides = payload.get("overrides", current["overrides"])
    images    = current.get("images", {})

    save_mapping(MAPPING_JSON_FILE, auto, overrides, images)
    return {"status": "ok"}


# -----------------------------
# ✅ Utility: Get fresh ERP/WC + mapping
# -----------------------------
async def get_fresh_data():
    erp_items   = get_erpnext_items()
    wc_products = await get_wc_products()

    auto_rows, overrides, images_map = build_or_load_mapping(
        MAPPING_JSON_FILE, wc_products, erp_items
    )
    apply_overrides(auto_rows, overrides)

    wc_by_id  = {p["id"]: p for p in wc_products}
    wc_by_sku = {p["sku"]: p for p in wc_products if p.get("sku")}

    # scrub stale links so deleted Woo items reappear for "create"
    if _scrub_stale_links(auto_rows, wc_by_id, wc_by_sku):
        save_mapping(MAPPING_JSON_FILE, auto_rows, overrides, images_map)

    erp_index = {i["item_code"]: i for i in erp_items}
    wc_index  = wc_by_sku
    return erp_index, wc_index, auto_rows, overrides, images_map


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
    pricelist, erp_index, wc_index, auto_rows, overrides, images_map = None, *await get_fresh_data()
    pricelist = await get_default_pricelist()

    created: List[str] = []
    failed:  List[str] = []
    manual_delete: List[str] = []
    errors:  Dict[str, str] = {}

    for row in auto_rows:
        code = row["erp_item_code"]

        if row.get("wc_product_id") or code in wc_index:
            continue

        price = await get_price_from_pricelist(None, code, pricelist)
        if price is None:
            failed.append(code)
            errors[code] = "No price found in pricelist"
            continue

        payload = map_erp_to_wc_product(erp_index[code], price)

        # initial cleanup
        await _ensure_sku_free(code)
        await asyncio.sleep(0.5)

        wc_p = None
        try:
            wc_p = await wc_create("products", payload)
        except HTTPStatusError as e_first:
            msg_first = str(e_first)
            dup = ("woocommerce_rest_product_not_created" in msg_first
                   and "already present in the lookup table" in msg_first)
            if dup:
                await _ensure_sku_free(code)
                await asyncio.sleep(0.5)
                if await wc_regenerate_lookup_table():
                    try:
                        wc_p = await wc_create("products", payload)
                    except Exception:
                        manual_delete.append(code)
                        errors[code] = msg_first
                        continue
                else:
                    manual_delete.append(code)
                    errors[code] = msg_first
                    continue
            else:
                failed.append(code)
                errors[code] = msg_first
                logger.error(f"[Create] {code} failed: {msg_first}")
                continue
        except Exception as e:
            failed.append(code)
            errors[code] = str(e)
            logger.error(f"[Create] {code} failed: {e}")
            continue

        # success
        row.update({
            "wc_product_id": wc_p["id"],
            "wc_sku"       : wc_p.get("sku") or code,
            "status"       : "created",
            "last_price"   : price,
            "last_synced"  : datetime.utcnow().isoformat() + "Z",
        })
        created.append(code)
        await sync_item_images(code, wc_p["id"], images_map, dry_run=False)

    save_mapping(MAPPING_JSON_FILE, auto_rows, overrides, images_map)
    return {
        "created": created,
        "failed": failed,
        "manual_delete": manual_delete,
        "errors": errors
    }


@admin_router.post("/api/sync/update")
async def bulk_update():
    pricelist = await get_default_pricelist()
    erp_index, wc_index, auto_rows, overrides, images_map = await get_fresh_data()

    updated: List[str] = []
    failed:  List[str] = []
    errors:  Dict[str, str] = {}

    for row in auto_rows:
        code = row["erp_item_code"]
        wc_p = wc_index.get(code)
        if not wc_p:
            continue

        price = await get_price_from_pricelist(None, code, pricelist)
        if price is None:
            failed.append(code)
            errors[code] = "No price found in pricelist"
            continue

        desired = map_erp_to_wc_product(erp_index[code], price)

        try:
            if needs_update(desired, wc_p):
                await wc_update(f"products/{wc_p['id']}", desired)
            await sync_item_images(code, wc_p["id"], images_map, dry_run=False)

            row.update({
                "status": "updated",
                "last_price": price,
                "last_synced": datetime.utcnow().isoformat() + "Z",
            })
            updated.append(code)
        except HTTPStatusError as e:
            failed.append(code)
            errors[code] = str(e)
            logger.error(f"[Update] {code} failed: {e}")
        except Exception as e:
            failed.append(code)
            errors[code] = str(e)
            logger.error(f"[Update] {code} failed: {e}")

    save_mapping(MAPPING_JSON_FILE, auto_rows, overrides, images_map)
    return {"updated": updated, "failed": failed, "errors": errors}


@admin_router.post("/api/sync/delete")
async def bulk_delete():
    erp_index, wc_index, auto_rows, overrides, images_map = await get_fresh_data()
    erp_codes = set(erp_index.keys())

    deleted: List[str] = []
    failed:  List[str] = []
    errors:  Dict[str, str] = {}

    for sku, wc_p in wc_index.items():
        if sku not in erp_codes:
            try:
                await wc_delete(f"products/{wc_p['id']}")
                deleted.append(sku)
            except HTTPStatusError as e:
                failed.append(sku)
                errors[sku] = str(e)
                logger.error(f"[Delete] {sku} failed: {e}")
            except Exception as e:
                failed.append(sku)
                errors[sku] = str(e)
                logger.error(f"[Delete] {sku} failed: {e}")

    save_mapping(MAPPING_JSON_FILE, auto_rows, overrides, images_map)
    return {"deleted": deleted, "failed": failed, "errors": errors}


@admin_router.post("/api/full-sync")
@admin_router.post("/api/resync")
async def full_sync_handler():
    pricelist = await get_default_pricelist()
    return await sync_products(pricelist=pricelist)


# ===================================
# ✅ New: Empty WooCommerce Trash 🗑️
# ===================================
@admin_router.post("/api/empty-trash")
async def empty_trash():
    """
    Permanently delete all products currently in WooCommerce 'trash' status.
    """
    removed: List[int] = []
    errors:  Dict[int, str] = {}
    page = 1

    while True:
        # fetch up to 100 trashed products per page
        trashed = await wc_get(
            "products",
            {"status": "trash", "per_page": 100, "page": page}
        )
        if not trashed:
            break

        for prod in trashed:
            pid = prod.get("id")
            try:
                # wc_delete always uses force=true
                await wc_delete(f"products/{pid}")
                removed.append(pid)
            except Exception as e:
                errors[pid] = str(e)

        page += 1

    return {"removed": removed, "errors": errors}
