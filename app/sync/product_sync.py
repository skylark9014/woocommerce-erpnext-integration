# =============================
# Product Sync Module
# - Syncs ERPNext items to WooCommerce
# - Handles create, update, delete, and mapping persistence
# =============================

import httpx
import logging
from datetime import datetime

from app.config import MAPPING_JSON_FILE, DEFAULT_PRICE_LIST
from app.erp.erp_fetch import get_erpnext_items, get_price_from_pricelist
from app.woocommerce.wc_fetch import get_wc_products
from app.mapping.mapping_store import build_or_load_mapping, apply_overrides, save_mapping
from app.woocommerce.woocommerce_api import wc_create, wc_update, wc_delete

logger = logging.getLogger(__name__)


async def sync_products():
    """
    Performs full product synchronization from ERPNext to WooCommerce.
    - Fetches ERP and WC products
    - Builds or loads product mapping
    - Creates, updates, and deletes WC products as needed
    - Saves updated mapping

    Returns a summary dictionary with status, action counts, and mapping metadata.
    """
    logger.info("[SyncProducts] START")
    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping(MAPPING_JSON_FILE, wc_products, erp_items)
    apply_overrides(auto_rows, overrides)

    erp_index = {i["item_code"]: i for i in erp_items}
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}

    created, updated, deleted, failed = [], [], [], []

    async with httpx.AsyncClient() as client:
        # CREATE
        for row in auto_rows:
            code = row["erp_item_code"]
            if row.get("wc_product_id") or code in wc_index:
                continue
            price = await get_price_from_pricelist(client, code, DEFAULT_PRICE_LIST)
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
                logger.error(f"[SyncProducts] Create fail {code}: {e}")
                failed.append(code)

        # UPDATE
        for row in auto_rows:
            code = row["erp_item_code"]
            wc_p = wc_index.get(code)
            if not wc_p:
                continue
            price = await get_price_from_pricelist(client, code, DEFAULT_PRICE_LIST)
            if price is None:
                failed.append(code)
                continue
            desired = map_erp_to_wc_product(erp_index[code], price)
            if any(str(desired.get(f)) != str(wc_p.get(f)) for f in ("name", "regular_price", "description", "short_description")):
                try:
                    wc_update(f"products/{wc_p['id']}", desired)
                    row.update({
                        "status": "updated",
                        "last_price": price,
                        "last_synced": datetime.utcnow().isoformat() + "Z"
                    })
                    updated.append(code)
                except Exception as e:
                    logger.error(f"[SyncProducts] Update fail {code}: {e}")
                    failed.append(code)

        # DELETE (WC products not in ERP)
        erp_codes = set(erp_index.keys())
        for sku, wc_p in wc_index.items():
            if sku not in erp_codes:
                try:
                    wc_delete(f"products/{wc_p['id']}")
                    deleted.append(sku)
                except Exception as e:
                    logger.error(f"[SyncProducts] Delete fail {sku}: {e}")
                    failed.append(sku)

    try:
        save_mapping(MAPPING_JSON_FILE, auto_rows, overrides)
    except Exception as e:
        logger.error("Failed to save product_mapping.json: %s", e)
        return {
            "status": "error",
            "summary": {
                "created": len(created),
                "updated": len(updated),
                "deleted": len(deleted),
                "failed": failed
            },
            "error": f"Failed to persist mapping: {e.__class__.__name__}: {e}"
        }

    return {
        "status": "error" if failed else "success",
        "summary": {
            "created": len(created),
            "updated": len(updated),
            "deleted": len(deleted),
            "failed": failed
        },
        "mapping_rows": len(auto_rows)
    }

# =============================
# 🔁 Selective Product Sync (bulk)
# =============================

async def sync_products_bulk(action: str) -> dict:
    logger.info(f"[SyncProductsBulk] START {action.upper()}")
    erp_items = get_erpnext_items()
    wc_products = get_wc_products()
    auto_rows, overrides = build_or_load_mapping(MAPPING_JSON_FILE, wc_products, erp_items)
    apply_overrides(auto_rows, overrides)

    erp_index = {i["item_code"]: i for i in erp_items}
    wc_index = {p["sku"]: p for p in wc_products if p.get("sku")}

    created, updated, deleted, failed = [], [], [], []

    async with httpx.AsyncClient() as client:
        for row in auto_rows:
            code = row["erp_item_code"]
            wc_p = wc_index.get(code)
            price = await get_price_from_pricelist(client, code, DEFAULT_PRICE_LIST)

            if action == "create":
                if row.get("wc_product_id") or code in wc_index:
                    continue
                if price is None:
                    failed.append(code)
                    continue
                try:
                    payload = map_erp_to_wc_product(erp_index[code], price)
                    new_product = wc_create("products", payload)
                    row["wc_product_id"] = new_product["id"]
                    row["status"] = "created"
                    row["last_price"] = price
                    row["last_synced"] = datetime.utcnow().isoformat() + "Z"
                    created.append(code)
                except Exception as e:
                    logger.error(f"[BulkCreate] Failed for {code}: {e}")
                    failed.append(code)

            elif action == "update":
                if not wc_p:
                    continue
                if price is None:
                    failed.append(code)
                    continue
                desired = map_erp_to_wc_product(erp_index[code], price)
                needs_update = any(
                    str(desired.get(fld, "")) != str(wc_p.get(fld, ""))
                    for fld in ("name", "regular_price", "description", "short_description")
                )
                if not needs_update:
                    continue
                try:
                    wc_update(f"products/{wc_p['id']}", desired)
                    row["status"] = "updated"
                    row["last_price"] = price
                    row["last_synced"] = datetime.utcnow().isoformat() + "Z"
                    updated.append(code)
                except Exception as e:
                    logger.error(f"[BulkUpdate] Failed for {code}: {e}")
                    failed.append(code)

            elif action == "delete":
                if code in erp_index:
                    continue
                try:
                    wc_delete(f"products/{wc_p['id']}")
                    deleted.append(code)
                except Exception as e:
                    logger.error(f"[BulkDelete] Failed for {code}: {e}")
                    failed.append(code)

    try:
        save_mapping(MAPPING_JSON_FILE, auto_rows, overrides)
    except Exception as e:
        logger.error(f"[SyncProductsBulk] Failed to save mapping: {e}")
        failed.append("!mapping_save")

    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "failed": failed
    }

